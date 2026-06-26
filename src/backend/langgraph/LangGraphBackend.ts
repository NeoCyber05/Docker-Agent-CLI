import * as fs from "node:fs";
import * as path from "node:path";
import type { Tool } from "src/Tool";
import { loadUserConfig } from "src/config";
import type { LoopContext } from "src/loopContext";
import { isDestroyAllPrompt, parseDirectDestroyStack } from "src/slashDispatch";
import { destroyAllStacks } from "src/tools/destroyAllStacks";
import { destroyStack } from "src/tools/destroyStack";
import type { LoopEvent } from "src/types/events";
import { AsyncQueue } from "src/utils/AsyncQueue";
import { PolicyEngine } from "../../policy/PolicyEngine";
import type { AgentBackend, BackendQueryParams } from "../AgentBackend";
import type { AgentState } from "./state";

async function* runTool<TIn, TOut>(
  tool: Tool<TIn, TOut>,
  input: TIn,
  ctx: LoopContext,
): AsyncGenerator<LoopEvent, TOut> {
  yield { type: "tool_call", name: tool.name, input };
  const gen = tool.call(input, ctx);
  let result: TOut;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      result = r.value;
      break;
    }
    yield { type: "tool_progress", msg: r.value.msg };
  }
  yield { type: "tool_result", name: tool.name, output: result };
  return result;
}

export class LangGraphBackend implements AgentBackend {
  readonly name = "langgraph" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    const queue = new AsyncQueue<LoopEvent>();
    const emit = (ev: LoopEvent) => queue.push(ev);

    const runner = (async () => {
      try {
        const userConfig = loadUserConfig();
        const rootPolicyPath = path.join(params.ctx.cwd, "project-policies.yaml");
        const legacyPolicyPath = path.join(params.ctx.cwd, ".docker-agent", "policies.yaml");
        let projectPolicyPath = fs.existsSync(rootPolicyPath) ? rootPolicyPath : legacyPolicyPath;

        if (!fs.existsSync(rootPolicyPath) && !fs.existsSync(legacyPolicyPath)) {
          const mode = userConfig.defaults?.missingProjectPolicy ?? "deny";
          if (mode === "deny") {
            const defaultContent = "project:\n  hardDeny: []\n  require: []\n";
            const resp = await params.ctx.requestPermission("initialize_project_policy", {
              reason:
                "Project policy file (project-policies.yaml) is missing but required by configuration.",
              path: rootPolicyPath,
              content: defaultContent,
            });
            if (resp.kind === "approve" || resp.kind === "always_allow_in_session") {
              try {
                fs.writeFileSync(rootPolicyPath, defaultContent, "utf-8");
                projectPolicyPath = rootPolicyPath;
                queue.push({
                  type: "assistant_text",
                  delta: `[docker-agent] Initialized default project policy at ${rootPolicyPath}\n`,
                });
              } catch (err) {
                queue.push({
                  type: "assistant_text",
                  delta: `[docker-agent] Failed to initialize project policy: ${(err as Error).message}\n`,
                });
              }
            }
          }
        }

        const policyEngine = new PolicyEngine({
          userConfig,
          projectPolicyPath,
        });

        const messages = [...params.messages];
        const lastUser = [...messages]
          .reverse()
          .find((m): m is { role: "user"; content: string } => m.role === "user");

        if (lastUser && isDestroyAllPrompt(lastUser.content)) {
          const typed = await params.ctx.requestTypedConfirm(
            "DESTROY ALL",
            `This will destroy ${params.ctx.stateStore.list().length} stacks.`,
          );
          if (typed.kind !== "typed_confirm_value" || typed.value !== "DESTROY ALL") {
            queue.push({
              type: "assistant_text",
              delta: "destroy_all aborted: typed confirmation did not match",
            });
            return;
          }
          const parsed = destroyAllStacks.inputSchema.parse({});
          for await (const ev of runTool(destroyAllStacks, parsed, params.ctx)) {
            queue.push(ev);
          }
          return;
        }

        const directDestroy = lastUser ? parseDirectDestroyStack(lastUser.content) : null;
        if (directDestroy) {
          const input = destroyStack.inputSchema.parse({
            stackName: directDestroy.stackName,
            ...(directDestroy.removeVolumes ? { removeVolumes: true } : {}),
          });
          if (directDestroy.removeVolumes) {
            const phrase = `DESTROY ${directDestroy.stackName}`;
            const typed = await params.ctx.requestTypedConfirm(
              phrase,
              `This will destroy the stack ${directDestroy.stackName} and delete all its volumes.`,
            );
            if (typed.kind !== "typed_confirm_value" || typed.value !== phrase) {
              queue.push({
                type: "assistant_text",
                delta: "destroy_stack aborted: typed confirmation did not match",
              });
              return;
            }
          } else if (!params.ctx.allowSet.has("destroy_stack")) {
            const resp = await params.ctx.requestPermission("destroy_stack", input);
            if (resp.kind === "deny") {
              queue.push({
                type: "assistant_text",
                delta: "destroy_stack aborted: permission denied",
              });
              return;
            }
            if (resp.kind === "always_allow_in_session") params.ctx.allowSet.add("destroy_stack");
          }
          for await (const ev of runTool(destroyStack, input, params.ctx)) {
            queue.push(ev);
          }
          return;
        }

        const { buildGraph } = await import("./graph");
        const graph = buildGraph({
          provider: params.provider,
          ctx: params.ctx,
          ...(params.model !== undefined ? { model: params.model } : {}),
          emit,
          policyEngine,
        });
        const initialState: typeof AgentState.State = {
          messages: params.messages,
          iter: 0,
          allowSet: params.ctx.allowSet,
          pendingToolResults: [],
          aborted: false,
        };
        const stream = await graph.stream(initialState, {
          streamMode: "values",
          recursionLimit: 50,
          signal: params.ctx.abortSignal,
        });
        for await (const _state of stream) {
          if (params.ctx.abortSignal.aborted) break;
          // Events are already emitted by node callbacks via `emit`.
        }
      } catch (err) {
        if (!params.ctx.abortSignal.aborted) {
          queue.push({ type: "error", error: err as Error });
        }
      } finally {
        queue.close();
      }
    })();

    for await (const ev of queue) yield ev;
    await runner;
  }
}

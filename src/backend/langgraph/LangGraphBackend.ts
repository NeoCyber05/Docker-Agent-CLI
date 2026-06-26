import * as fs from "node:fs";
import * as path from "node:path";
import { loadUserConfig } from "src/config";
import type { LoopEvent } from "src/types/events";
import { AsyncQueue } from "src/utils/AsyncQueue";
import { PolicyEngine } from "../../policy/PolicyEngine";
import type { AgentBackend, BackendQueryParams } from "../AgentBackend";
import type { AgentState } from "./state";

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
          progress: [],
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

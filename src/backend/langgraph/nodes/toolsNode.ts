import { type Tool, findToolByName } from "src/Tool";
import type { LoopContext } from "src/loopContext";
import { getAgentTools } from "src/tools";
import type { DestroyStackInput } from "src/tools/destroyStack";
import type { LoopEvent } from "src/types/events";
import { runTool } from "../adapters/toolAdapter";
import type { AgentState, PendingToolResult } from "../state";

const READ_ONLY_ALLOWLIST = new Set([
  "validate_spec",
  "resolve_dependency",
  "check_port_conflict",
  "list_stacks",
  "inspect_drift",
  "get_stack_status",
  "get_health",
  "get_logs",
  "pull_image",
  "exec_docker",
]);

export interface ToolsNodeDeps {
  ctx: LoopContext;
  emit: (ev: LoopEvent) => void;
}

async function executeToolUse(
  tool: Tool,
  parsed: unknown,
  tu: { id?: string; name?: string; input?: unknown },
  ctx: LoopContext,
  emit: (ev: LoopEvent) => void,
): Promise<PendingToolResult> {
  const run = await runTool(tool, parsed, ctx);
  for (const p of run.progress) emit({ type: "tool_progress", msg: p.msg });
  emit({ type: "tool_result", name: tool.name, output: run.output });
  return {
    toolUseId: tu.id as string,
    name: tool.name,
    input: parsed,
    output: run.output,
    isError: run.isError,
  };
}

export const toolsNode =
  ({ ctx, emit }: ToolsNodeDeps) =>
  async (state: typeof AgentState.State) => {
    const assistantMsg = state.messages[state.messages.length - 1];
    if (!assistantMsg || assistantMsg.role !== "assistant") return {};
    const toolUses = (
      assistantMsg.content as Array<{ type: string; id?: string; name?: string; input?: unknown }>
    ).filter(
      (b) => b.type === "tool_use" && b.name !== "plan_stack" && b.name !== "remediate_drift",
    );

    const results: PendingToolResult[] = [];
    for (const tu of toolUses) {
      if (ctx.abortSignal.aborted) break;

      const tool = findToolByName(getAgentTools(), tu.name as string);
      if (!tool) {
        // No LoopEvent emitted for unknown tools; only push the tool message.
        results.push({
          toolUseId: tu.id as string,
          name: tu.name as string,
          input: tu.input,
          output: `unknown tool: ${tu.name}`,
          isError: true,
        });
        continue;
      }

      let parsed: unknown;
      try {
        parsed = tool.inputSchema.parse(tu.input);
      } catch (err) {
        const msg = `validation failed: ${err instanceof Error ? err.message : String(err)}`;
        // No LoopEvent emitted for validation failures; only push the tool message.
        results.push({
          toolUseId: tu.id as string,
          name: tool.name,
          input: tu.input,
          output: msg,
          isError: true,
        });
        continue;
      }

      // Special handling for destroy_all_stacks: typed DESTROY ALL confirmation.
      if (tool.name === "destroy_all_stacks") {
        const typed = await ctx.requestTypedConfirm(
          "DESTROY ALL",
          `This will destroy ${ctx.stateStore.list().length} stacks.`,
        );
        if (typed.kind !== "typed_confirm_value" || typed.value !== "DESTROY ALL") {
          results.push({
            toolUseId: tu.id as string,
            name: tool.name,
            input: parsed,
            output: "destroy_all aborted: typed confirmation did not match",
            isError: false,
          });
          continue;
        }
        emit({ type: "tool_call", name: tool.name, input: parsed });
        results.push(await executeToolUse(tool, parsed, tu, ctx, emit));
        continue;
      }

      // destroy_stack with --volumes requires typed confirmation and bypasses the
      // normal permission gate (matches src/query.ts:707-724).
      if (tool.name === "destroy_stack") {
        const { stackName, removeVolumes } = parsed as DestroyStackInput;
        if (removeVolumes) {
          const phrase = `DESTROY ${stackName}`;
          const typed = await ctx.requestTypedConfirm(
            phrase,
            `This will destroy the stack ${stackName} and delete all its volumes.`,
          );
          if (typed.kind !== "typed_confirm_value" || typed.value !== phrase) {
            results.push({
              toolUseId: tu.id as string,
              name: tool.name,
              input: parsed,
              output: "destroy_stack aborted: typed confirmation did not match",
              isError: false,
            });
            continue;
          }
          emit({ type: "tool_call", name: tool.name, input: parsed });
          results.push(await executeToolUse(tool, parsed, tu, ctx, emit));
          continue;
        }
      }

      // Normal allowlisted path: read-only/utility tools and destroy_stack without
      // --volumes run here. Destructive variants are handled above.
      if (!READ_ONLY_ALLOWLIST.has(tool.name) && tool.name !== "destroy_stack") {
        // No LoopEvent emitted for unsupported tools; only push the tool message.
        results.push({
          toolUseId: tu.id as string,
          name: tool.name,
          input: parsed,
          output: "tool not supported in langgraph backend (phase 3)",
          isError: true,
        });
        continue;
      }

      // Permission gating (mirror src/query.ts:738-752).
      if (tool.needsPermission(parsed) && !ctx.allowSet.has(tool.name)) {
        const resp = await ctx.requestPermission(tool.name, parsed);
        if (resp.kind === "deny") {
          // No LoopEvent emitted for permission denials; only push the tool message.
          results.push({
            toolUseId: tu.id as string,
            name: tool.name,
            input: parsed,
            output: "User denied permission.",
            isError: false,
          });
          continue;
        }
        if (resp.kind === "always_allow_in_session") {
          ctx.allowSet.add(tool.name);
        }
      }

      emit({ type: "tool_call", name: tool.name, input: parsed });

      results.push(await executeToolUse(tool, parsed, tu, ctx, emit));
    }
    const toolMessages = results.map((r) => ({
      role: "tool" as const,
      toolUseId: r.toolUseId,
      content: typeof r.output === "string" ? r.output : JSON.stringify(r.output),
      isError: r.isError,
    }));
    return { messages: toolMessages, pendingToolResults: results };
  };

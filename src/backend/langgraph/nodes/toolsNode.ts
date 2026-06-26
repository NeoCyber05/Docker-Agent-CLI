import { findToolByName } from "src/Tool";
import type { LoopContext } from "src/loopContext";
import { getAgentTools } from "src/tools";
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

export const toolsNode =
  ({ ctx, emit }: ToolsNodeDeps) =>
  async (state: typeof AgentState.State) => {
    const assistantMsg = state.messages[state.messages.length - 1];
    if (!assistantMsg || assistantMsg.role !== "assistant") return {};
    const toolUses = (
      assistantMsg.content as Array<{ type: string; id?: string; name?: string; input?: unknown }>
    ).filter((b) => b.type === "tool_use");
    const results: PendingToolResult[] = [];
    for (const tu of toolUses) {
      if (ctx.abortSignal.aborted) break;

      const tool = findToolByName(getAgentTools(), tu.name as string);
      if (!tool) {
        emit({
          type: "tool_result",
          name: tu.name as string,
          output: `unknown tool: ${tu.name}`,
        });
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
        // NO tool_call emitted for validation failure (matches CurrentBackend)
        emit({
          type: "tool_result",
          name: tool.name,
          output: msg,
        });
        results.push({
          toolUseId: tu.id as string,
          name: tool.name,
          input: tu.input,
          output: msg,
          isError: true,
        });
        continue;
      }

      // Phase 3 read-only allowlist: only read-only/escape-hatch tools supported in LangGraph backend
      if (!READ_ONLY_ALLOWLIST.has(tool.name)) {
        emit({ type: "tool_call", name: tool.name, input: parsed });
        emit({
          type: "tool_result",
          name: tool.name,
          output: "tool not supported in langgraph backend (phase 3)",
        });
        results.push({
          toolUseId: tu.id as string,
          name: tool.name,
          input: parsed,
          output: "tool not supported in langgraph backend (phase 3)",
          isError: true,
        });
        continue;
      }

      // Permission gating (mirror src/query.ts:738-752)
      if (tool.needsPermission(parsed) && !ctx.allowSet.has(tool.name)) {
        const resp = await ctx.requestPermission(tool.name, parsed);
        if (resp.kind === "deny") {
          emit({
            type: "tool_result",
            name: tool.name,
            output: "User denied permission.",
          });
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

      const run = await runTool(tool, parsed, ctx);
      for (const p of run.progress) emit({ type: "tool_progress", msg: p.msg });
      emit({ type: "tool_result", name: tool.name, output: run.output });
      results.push({
        toolUseId: tu.id as string,
        name: tool.name,
        input: parsed,
        output: run.output,
        isError: run.isError,
      });
    }
    const toolMessages = results.map((r) => ({
      role: "tool" as const,
      toolUseId: r.toolUseId,
      content: typeof r.output === "string" ? r.output : JSON.stringify(r.output),
      isError: r.isError,
    }));
    return { messages: toolMessages, pendingToolResults: results };
  };

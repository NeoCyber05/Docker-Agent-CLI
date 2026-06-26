import { findToolByName } from "src/Tool";
import type { LoopContext } from "src/loopContext";
import { getAgentTools } from "src/tools";
import type { LoopEvent } from "src/types/events";
import { runTool } from "../adapters/toolAdapter";
import type { AgentState, PendingToolResult } from "../state";

const READ_ONLY_ALLOWLIST = new Set([
  "list_stacks",
  "inspect_drift",
  "get_stack_status",
  "get_health",
  "get_logs",
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
      emit({ type: "tool_call", name: tu.name as string, input: tu.input });
      if (!READ_ONLY_ALLOWLIST.has(tu.name as string)) {
        emit({
          type: "tool_result",
          name: tu.name as string,
          output: "tool not supported in langgraph backend (phase 2)",
        });
        results.push({
          toolUseId: tu.id as string,
          name: tu.name as string,
          input: tu.input,
          output: "tool not supported in langgraph backend (phase 2)",
          isError: true,
        });
        continue;
      }
      const tool = findToolByName(getAgentTools(), tu.name as string);
      if (!tool) {
        results.push({
          toolUseId: tu.id as string,
          name: tu.name as string,
          input: tu.input,
          output: `unknown tool: ${tu.name}`,
          isError: true,
        });
        continue;
      }
      const run = await runTool(tool, tu.input, ctx);
      for (const p of run.progress) emit({ type: "tool_progress", msg: p.msg });
      emit({ type: "tool_result", name: tu.name as string, output: run.output });
      results.push({
        toolUseId: tu.id as string,
        name: tu.name as string,
        input: tu.input,
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

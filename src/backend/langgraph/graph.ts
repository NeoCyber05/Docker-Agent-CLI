import { END, StateGraph } from "@langchain/langgraph";
import { type AgentNodeDeps, MAX_ITERATIONS, agentNode } from "./nodes/agentNode";
import { type ToolsNodeDeps, toolsNode } from "./nodes/toolsNode";
import { AgentState } from "./state";

export interface GraphDeps extends AgentNodeDeps, ToolsNodeDeps {
  model?: string;
  provider: AgentNodeDeps["provider"];
  ctx: AgentNodeDeps["ctx"];
  emit: AgentNodeDeps["emit"];
}

export function buildGraph(deps: GraphDeps) {
  const agentNodeDeps: AgentNodeDeps = {
    provider: deps.provider,
    ctx: deps.ctx,
    emit: deps.emit,
    ...(deps.model !== undefined ? { model: deps.model } : {}),
  };
  const g = new StateGraph(AgentState)
    .addNode("agent", agentNode(agentNodeDeps))
    .addNode("tools", toolsNode({ ctx: deps.ctx, emit: deps.emit }))
    .addEdge("__start__", "agent")
    .addConditionalEdges("agent", (state: typeof AgentState.State) => {
      const last = state.messages[state.messages.length - 1];
      const hasToolUse =
        last?.role === "assistant" &&
        Array.isArray(last.content) &&
        (last.content as Array<{ type: string }>).some((b) => b.type === "tool_use");
      if (!hasToolUse) return END;
      if (state.iter >= MAX_ITERATIONS) return END;
      return "tools";
    })
    .addEdge("tools", "agent");
  return g.compile();
}

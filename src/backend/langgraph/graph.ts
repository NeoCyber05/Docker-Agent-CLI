import { END, StateGraph } from "@langchain/langgraph";
import type { PolicyEngine } from "src/policy/PolicyEngine";
import { type AgentNodeDeps, MAX_ITERATIONS, agentNode } from "./nodes/agentNode";
import { planReviewNode } from "./nodes/planReviewNode";
import { type ToolsNodeDeps, toolsNode } from "./nodes/toolsNode";
import { AgentState } from "./state";

export interface GraphDeps extends AgentNodeDeps, ToolsNodeDeps {
  model?: string;
  provider: AgentNodeDeps["provider"];
  ctx: AgentNodeDeps["ctx"];
  emit: AgentNodeDeps["emit"];
  policyEngine: PolicyEngine;
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
    .addNode(
      "plan_review",
      planReviewNode({ ctx: deps.ctx, policyEngine: deps.policyEngine, emit: deps.emit }),
    )
    .addEdge("__start__", "agent")
    .addConditionalEdges("agent", (state: typeof AgentState.State) => {
      const last = state.messages[state.messages.length - 1];
      const toolUses =
        last?.role === "assistant" && Array.isArray(last.content)
          ? (last.content as Array<{ type: string; name?: string }>).filter(
              (b) => b.type === "tool_use",
            )
          : [];
      if (toolUses.length === 0) return END;
      if (state.iter > MAX_ITERATIONS) return END;
      if (toolUses.some((b) => b.name === "plan_stack")) return "plan_review";
      return "tools";
    })
    .addConditionalEdges("plan_review", (state: typeof AgentState.State) => {
      const assistantMsg = [...state.messages].reverse().find((m) => m.role === "assistant");
      const remaining =
        assistantMsg && Array.isArray(assistantMsg.content)
          ? (assistantMsg.content as Array<{ type: string; name?: string }>).filter(
              (b) => b.type === "tool_use" && b.name !== "plan_stack",
            )
          : [];
      return remaining.length > 0 ? "tools" : "agent";
    })
    .addEdge("tools", "agent");
  return g.compile();
}

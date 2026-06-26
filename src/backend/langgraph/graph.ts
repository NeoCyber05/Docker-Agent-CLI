import { END, StateGraph } from "@langchain/langgraph";
import type { PolicyEngine } from "src/policy/PolicyEngine";
import { type AgentNodeDeps, MAX_ITERATIONS, agentNode } from "./nodes/agentNode";
import { planReviewNode } from "./nodes/planReviewNode";
import { remediateDriftNode } from "./nodes/remediateDriftNode";
import { type ToolsNodeDeps, toolsNode } from "./nodes/toolsNode";
import { AgentState } from "./state";

export interface GraphDeps extends AgentNodeDeps, ToolsNodeDeps {
  model?: string;
  provider: AgentNodeDeps["provider"];
  ctx: AgentNodeDeps["ctx"];
  emit: AgentNodeDeps["emit"];
  policyEngine: PolicyEngine;
}

function toolUsesInLastAssistant(state: typeof AgentState.State) {
  const last = state.messages[state.messages.length - 1];
  if (!last || last.role !== "assistant" || !Array.isArray(last.content)) return [];
  return (last.content as Array<{ type: string; name?: string }>).filter(
    (b) => b.type === "tool_use",
  );
}

function routeAfterSpecialNode(
  state: typeof AgentState.State,
  excludeTool: "plan_stack" | "remediate_drift",
): "plan_review" | "remediate_drift" | "tools" | "agent" {
  const assistantMsg = [...state.messages].reverse().find((m) => m.role === "assistant");
  const remaining =
    assistantMsg && Array.isArray(assistantMsg.content)
      ? (assistantMsg.content as Array<{ type: string; name?: string }>).filter(
          (b) => b.type === "tool_use" && b.name !== excludeTool,
        )
      : [];

  const otherSpecial: "plan_stack" | "remediate_drift" =
    excludeTool === "plan_stack" ? "remediate_drift" : "plan_stack";
  const otherNode: "plan_review" | "remediate_drift" =
    excludeTool === "plan_stack" ? "remediate_drift" : "plan_review";

  if (remaining.some((b) => b.name === otherSpecial)) return otherNode;
  const nonSpecial = remaining.filter((b) => b.name !== otherSpecial);
  return nonSpecial.length > 0 ? "tools" : "agent";
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
    .addNode(
      "remediate_drift",
      remediateDriftNode({ ctx: deps.ctx, policyEngine: deps.policyEngine, emit: deps.emit }),
    )
    .addEdge("__start__", "agent")
    .addConditionalEdges("agent", (state: typeof AgentState.State) => {
      const toolUses = toolUsesInLastAssistant(state);
      if (toolUses.length === 0) return END;
      if (state.iter > MAX_ITERATIONS) return END;
      if (toolUses.some((b) => b.name === "remediate_drift")) return "remediate_drift";
      if (toolUses.some((b) => b.name === "plan_stack")) return "plan_review";
      return "tools";
    })
    .addConditionalEdges("remediate_drift", (state: typeof AgentState.State) => {
      if (state.aborted) return END;
      return routeAfterSpecialNode(state, "remediate_drift");
    })
    .addConditionalEdges("plan_review", (state: typeof AgentState.State) => {
      if (state.aborted) return END;
      return routeAfterSpecialNode(state, "plan_stack");
    })
    .addEdge("tools", "agent");
  return g.compile();
}

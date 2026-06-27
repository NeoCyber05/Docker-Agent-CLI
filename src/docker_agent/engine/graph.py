"""Compiled LangGraph state machine.

Parity: ``src/backend/langgraph/graph.ts``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from docker_agent.engine.nodes.agent_node import (
    MAX_ITERATIONS,
    AgentNodeDeps,
    agent_node,
)
from docker_agent.engine.nodes.plan_review_node import (
    PlanReviewNodeDeps,
    plan_review_node,
)
from docker_agent.engine.nodes.remediate_drift_node import (
    RemediateDriftNodeDeps,
    remediate_drift_node,
)
from docker_agent.engine.nodes.tools_node import ToolsNodeDeps, tools_node
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.services.api.types import Provider


def _block_type(block: Any) -> str | None:
    return getattr(block, "type", None)


def _tool_uses_in_last_assistant(state: AgentState) -> list[Any]:
    last = state.messages[-1] if state.messages else None
    if not last or last.role != "assistant" or not last.content:
        return []
    return [b for b in last.content if _block_type(b) == "tool_use"]


def _route_after_special_node(state: AgentState, exclude_tool: str) -> str:
    assistant = next((m for m in reversed(state.messages) if m.role == "assistant"), None)
    remaining = [
        b
        for b in (assistant.content if assistant else [])
        if _block_type(b) == "tool_use" and getattr(b, "name", None) != exclude_tool
    ]
    other_special = "remediate_drift" if exclude_tool == "plan_stack" else "plan_stack"
    other_node = "remediate_drift" if exclude_tool == "plan_stack" else "plan_review"
    if any(getattr(b, "name", None) == other_special for b in remaining):
        return other_node
    non_special = [b for b in remaining if getattr(b, "name", None) != other_special]
    return "tools" if non_special else "agent"


@dataclass
class GraphDeps:
    provider: Provider
    ctx: Any
    emit: Callable[[Any], None]
    policy_engine: PolicyEngine
    model: str | None = None


def build_graph(deps: GraphDeps) -> Any:
    agent_deps = AgentNodeDeps(
        provider=deps.provider,
        ctx=deps.ctx,
        emit=deps.emit,
        model=deps.model,
    )
    tools_deps = ToolsNodeDeps(ctx=deps.ctx, emit=deps.emit)
    plan_deps = PlanReviewNodeDeps(
        ctx=deps.ctx,
        policy_engine=deps.policy_engine,
        emit=deps.emit,
    )
    remediate_deps = RemediateDriftNodeDeps(
        ctx=deps.ctx,
        policy_engine=deps.policy_engine,
        emit=deps.emit,
    )

    async def agent_wrapper(state: AgentState) -> dict[str, Any]:
        return await agent_node(agent_deps, state)

    async def tools_wrapper(state: AgentState) -> dict[str, Any]:
        return await tools_node(tools_deps, state)

    async def plan_review_wrapper(state: AgentState) -> dict[str, Any]:
        return await plan_review_node(plan_deps, state)

    async def remediate_wrapper(state: AgentState) -> dict[str, Any]:
        return await remediate_drift_node(remediate_deps, state)

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_wrapper)
    builder.add_node("tools", tools_wrapper)
    builder.add_node("plan_review", plan_review_wrapper)
    builder.add_node("remediate_drift", remediate_wrapper)
    builder.add_edge("__start__", "agent")

    def route_after_agent(state: AgentState) -> str:
        tool_uses = _tool_uses_in_last_assistant(state)
        if not tool_uses:
            return END
        if state.iter > MAX_ITERATIONS:
            return END
        if any(getattr(b, "name", None) == "remediate_drift" for b in tool_uses):
            return "remediate_drift"
        if any(getattr(b, "name", None) == "plan_stack" for b in tool_uses):
            return "plan_review"
        return "tools"

    builder.add_conditional_edges("agent", route_after_agent)
    builder.add_conditional_edges(
        "remediate_drift",
        lambda state: END
        if state.aborted
        else _route_after_special_node(state, "remediate_drift"),
    )
    builder.add_conditional_edges(
        "plan_review",
        lambda state: END if state.aborted else _route_after_special_node(state, "plan_stack"),
    )
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=MemorySaver())
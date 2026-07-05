"""Explicit LangGraph topology for the production backend runtime."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from docker_agent.engine.langgraph.state import (
    LangGraphRuntimeState,
    RuntimeNode,
    RuntimeRoute,
)


def _next_route(default: RuntimeRoute) -> Any:
    def _route(state: LangGraphRuntimeState) -> str:
        route = state.get("route") or default
        return str(route)

    return _route


def build_langgraph_runtime_graph(
    *,
    context_loader_node: RuntimeNode,
    command_router_node: RuntimeNode,
    reasoning_node: RuntimeNode,
    tool_policy_gate_node: RuntimeNode,
    tool_call_node: RuntimeNode,
    human_approval_node: RuntimeNode,
    deploy_node: RuntimeNode,
    rollback_node: RuntimeNode,
    finalize_node: RuntimeNode,
) -> Any:
    """Build the explicit core orchestration graph."""

    builder = StateGraph(LangGraphRuntimeState)
    builder.add_node("context_loader", context_loader_node)
    builder.add_node("command_router", command_router_node)
    builder.add_node("reasoning", reasoning_node)
    builder.add_node("tool_policy_gate", tool_policy_gate_node)
    builder.add_node("tool_call", tool_call_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("deploy", deploy_node)
    builder.add_node("rollback", rollback_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "context_loader")
    builder.add_conditional_edges("context_loader", _next_route("command_router"))
    builder.add_conditional_edges("command_router", _next_route("reasoning"))
    builder.add_conditional_edges("reasoning", _next_route("finalize"))
    builder.add_conditional_edges("tool_policy_gate", _next_route("tool_call"))
    builder.add_conditional_edges("tool_call", _next_route("reasoning"))
    builder.add_conditional_edges("human_approval", _next_route("finalize"))
    builder.add_conditional_edges("deploy", _next_route("finalize"))
    builder.add_conditional_edges("rollback", _next_route("finalize"))
    builder.add_edge("finalize", END)
    return builder.compile()


__all__ = ["build_langgraph_runtime_graph"]
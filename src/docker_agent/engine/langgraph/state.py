"""Typed runtime state for the LangGraph control-plane graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

RuntimeRoute = Literal[
    "context_loader",
    "command_router",
    "reasoning",
    "tool_policy_gate",
    "tool_call",
    "human_approval",
    "deploy",
    "rollback",
    "finalize",
]


class LangGraphRuntimeState(TypedDict, total=False):
    route: RuntimeRoute | str
    handled: bool
    finalized: bool
    messages: list[Any]
    mcp_tools: list[Any]
    mcp_tools_by_name: dict[str, Any]
    model_visible_tools: list[Any]
    capabilities: dict[str, Any]
    context_summary: str
    provider_name: str
    model: str | None
    high_risk_tools: set[str]
    queued_tool_calls: list[dict[str, Any]]
    active_tool_call: dict[str, Any]
    pending_action: dict[str, Any]
    pending_tool_call: dict[str, Any]
    approval_decision: dict[str, Any]
    deploy_result: dict[str, Any]
    rollback_action: dict[str, Any]
    rollback_result: dict[str, Any]
    loop_count: int
    error: str


RuntimeNode = Callable[[LangGraphRuntimeState], Awaitable[dict[str, Any]]]


__all__ = ["LangGraphRuntimeState", "RuntimeNode", "RuntimeRoute"]
from __future__ import annotations

from typing import Any

import pytest

from infra_agent.engine.langgraph.graph import build_langgraph_runtime_graph


def _node(name: str, calls: list[str], result: dict[str, Any]):
    async def _run(state: dict[str, Any]) -> dict[str, Any]:
        del state
        calls.append(name)
        return result

    return _run


@pytest.mark.asyncio
async def test_runtime_graph_routes_handled_command_to_finalize() -> None:
    calls: list[str] = []
    graph = build_langgraph_runtime_graph(
        context_loader_node=_node("context_loader", calls, {"route": "command_router"}),
        command_router_node=_node(
            "command_router",
            calls,
            {"handled": True, "route": "finalize"},
        ),
        reasoning_node=_node("reasoning", calls, {}),
        tool_policy_gate_node=_node("tool_policy_gate", calls, {}),
        tool_call_node=_node("tool_call", calls, {}),
        human_approval_node=_node("human_approval", calls, {}),
        deploy_node=_node("deploy", calls, {}),
        rollback_node=_node("rollback", calls, {}),
        finalize_node=_node("finalize", calls, {"finalized": True}),
    )

    result = await graph.ainvoke({})

    assert result["handled"] is True
    assert result["finalized"] is True
    assert calls == ["context_loader", "command_router", "finalize"]


@pytest.mark.asyncio
async def test_runtime_graph_routes_tool_observation_back_to_reasoning() -> None:
    calls: list[str] = []
    reasoning_count = 0

    async def reasoning(state: dict[str, Any]) -> dict[str, Any]:
        del state
        nonlocal reasoning_count
        reasoning_count += 1
        calls.append("reasoning")
        if reasoning_count == 1:
            return {
                "queued_tool_calls": [{"name": "docker.list_stacks", "args": {}}],
                "route": "tool_policy_gate",
            }
        return {"route": "finalize"}

    async def tool_policy_gate(state: dict[str, Any]) -> dict[str, Any]:
        calls.append("tool_policy_gate")
        return {
            "active_tool_call": state["queued_tool_calls"][0],
            "queued_tool_calls": [],
            "route": "tool_call",
        }

    graph = build_langgraph_runtime_graph(
        context_loader_node=_node("context_loader", calls, {"route": "command_router"}),
        command_router_node=_node("command_router", calls, {"route": "reasoning"}),
        reasoning_node=reasoning,
        tool_policy_gate_node=tool_policy_gate,
        tool_call_node=_node("tool_call", calls, {"route": "reasoning"}),
        human_approval_node=_node("human_approval", calls, {}),
        deploy_node=_node("deploy", calls, {}),
        rollback_node=_node("rollback", calls, {}),
        finalize_node=_node("finalize", calls, {"finalized": True}),
    )

    result = await graph.ainvoke({})

    assert result["finalized"] is True
    assert calls == [
        "context_loader",
        "command_router",
        "reasoning",
        "tool_policy_gate",
        "tool_call",
        "reasoning",
        "finalize",
    ]


@pytest.mark.asyncio
async def test_runtime_graph_routes_pending_confirmation_to_deploy() -> None:
    calls: list[str] = []
    graph = build_langgraph_runtime_graph(
        context_loader_node=_node("context_loader", calls, {"route": "command_router"}),
        command_router_node=_node("command_router", calls, {"route": "reasoning"}),
        reasoning_node=_node(
            "reasoning",
            calls,
            {
                "queued_tool_calls": [{"name": "docker.deploy_stack", "args": {}}],
                "route": "tool_policy_gate",
            },
        ),
        tool_policy_gate_node=_node(
            "tool_policy_gate",
            calls,
            {"active_tool_call": {"name": "docker.deploy_stack"}, "route": "tool_call"},
        ),
        tool_call_node=_node(
            "tool_call",
            calls,
            {
                "pending_action": {"id": "pending-1", "kind": "plan_review"},
                "route": "human_approval",
            },
        ),
        human_approval_node=_node(
            "human_approval",
            calls,
            {"approval_decision": {"decision": "approve"}, "route": "deploy"},
        ),
        deploy_node=_node("deploy", calls, {"deploy_result": {"ok": True}, "route": "finalize"}),
        rollback_node=_node("rollback", calls, {}),
        finalize_node=_node("finalize", calls, {"finalized": True}),
    )

    result = await graph.ainvoke({})

    assert result["deploy_result"] == {"ok": True}
    assert calls == [
        "context_loader",
        "command_router",
        "reasoning",
        "tool_policy_gate",
        "tool_call",
        "human_approval",
        "deploy",
        "finalize",
    ]


@pytest.mark.asyncio
async def test_runtime_graph_routes_failed_deploy_to_rollback() -> None:
    calls: list[str] = []
    graph = build_langgraph_runtime_graph(
        context_loader_node=_node("context_loader", calls, {"route": "command_router"}),
        command_router_node=_node("command_router", calls, {"route": "deploy"}),
        reasoning_node=_node("reasoning", calls, {}),
        tool_policy_gate_node=_node("tool_policy_gate", calls, {}),
        tool_call_node=_node("tool_call", calls, {}),
        human_approval_node=_node("human_approval", calls, {}),
        deploy_node=_node(
            "deploy",
            calls,
            {
                "deploy_result": {"ok": False},
                "rollback_action": {"id": "rollback-1"},
                "route": "rollback",
            },
        ),
        rollback_node=_node(
            "rollback",
            calls,
            {"rollback_result": {"ok": True}, "route": "finalize"},
        ),
        finalize_node=_node("finalize", calls, {"finalized": True}),
    )

    result = await graph.ainvoke({})

    assert result["rollback_result"] == {"ok": True}
    assert calls == ["context_loader", "command_router", "deploy", "rollback", "finalize"]


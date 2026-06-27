"""Tests for tools_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.engine.nodes.tools_node import ToolsNodeDeps, tools_node
from src.engine.state import AgentState
from src.types.message import AssistantBlock, AssistantMessage


def _assistant_with_tool(name: str, input_data: object, tool_id: str = "t1") -> AgentState:
    block = AssistantBlock.model_validate(
        {"type": "tool_use", "id": tool_id, "name": name, "input": input_data}
    )
    return AgentState(
        messages=[AssistantMessage(content=[block])],
        iter=1,
    )


@pytest.mark.asyncio
async def test_tools_node_unknown_tool(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    deps = ToolsNodeDeps(ctx=ctx, emit=lambda _e: None)
    state = _assistant_with_tool("nonexistent_tool", {})

    result = await tools_node(deps, state)

    assert len(result["messages"]) == 1
    assert "unknown tool" in result["messages"][0].content
    assert result["messages"][0].is_error is True


@pytest.mark.asyncio
async def test_tools_node_allowlist_blocks_unsupported_tool(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    deps = ToolsNodeDeps(ctx=ctx, emit=lambda _e: None)
    state = _assistant_with_tool("apply_stack", {"stackName": "x", "composeYaml": "s:"})

    class FakeApplyTool:
        name = "apply_stack"
        input_schema = type(
            "Schema",
            (),
            {"model_validate": staticmethod(lambda x: x)},
        )()

        def needs_permission(self, _input: object) -> bool:
            return False

        async def call(self, _input: object, _ctx: object):
            yield

    with patch(
        "src.engine.nodes.tools_node.get_agent_tools",
        return_value=[FakeApplyTool()],
    ):
        result = await tools_node(deps, state)

    assert "not supported in langgraph backend" in result["messages"][0].content
    assert result["messages"][0].is_error is True


@pytest.mark.asyncio
async def test_tools_node_list_stacks_success(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    deps = ToolsNodeDeps(ctx=ctx, emit=events.append)
    state = _assistant_with_tool("list_stacks", {})

    result = await tools_node(deps, state)

    types = [getattr(e, "type", None) for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert result["messages"][0].is_error is False


@pytest.mark.asyncio
async def test_tools_node_permission_denied(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    ctx.request_permission = AsyncMock(return_value={"kind": "deny"})
    deps = ToolsNodeDeps(ctx=ctx, emit=lambda _e: None)
    state = _assistant_with_tool("destroy_stack", {"stackName": "demo"})

    result = await tools_node(deps, state)

    assert result["messages"][0].content == "User denied permission."
    assert result["messages"][0].is_error is False


@pytest.mark.asyncio
async def test_tools_node_destroy_stack_typed_confirm_mismatch(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    ctx.request_typed_confirm = AsyncMock(
        return_value={"kind": "typed_confirm_value", "value": "WRONG"}
    )
    deps = ToolsNodeDeps(ctx=ctx, emit=lambda _e: None)
    state = _assistant_with_tool(
        "destroy_stack",
        {"stackName": "demo", "removeVolumes": True},
    )

    result = await tools_node(deps, state)

    assert "typed confirmation did not match" in result["messages"][0].content
    assert result["messages"][0].is_error is False
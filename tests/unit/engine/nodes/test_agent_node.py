"""Tests for agent_node."""

from __future__ import annotations

import pytest

from docker_agent.engine.nodes.agent_node import AgentNodeDeps, agent_node
from docker_agent.engine.state import AgentState
from docker_agent.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
    UsageEvent,
)
from docker_agent.types.message import UserMessage


class FakeProvider:
    name = "fake"

    def __init__(self, events: list[object]) -> None:
        self._events = events

    async def stream(self, _params):
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_agent_node_emits_events_and_returns_assistant_message(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []

    provider = FakeProvider(
        [
            TextDeltaEvent(text="hello"),
            ToolUseStartEvent(id="t1", name="list_stacks"),
            ToolUseDeltaEvent(id="t1", args_partial_json="{}"),
            ToolUseStopEvent(id="t1"),
            UsageEvent(input_tokens=3, output_tokens=2),
            MessageStopEvent(stop_reason="tool_use"),
        ]
    )

    deps = AgentNodeDeps(provider=provider, ctx=ctx, emit=events.append)
    state = AgentState(messages=[UserMessage(content="hi")], iter=0)

    result = await agent_node(deps, state)

    types = [getattr(e, "type", None) for e in events]
    assert "iteration_start" in types
    assert "assistant_text" in types
    assert "usage" in types
    assert result["iter"] == 1
    assert len(result["messages"]) == 1
    assert result["messages"][0].role == "assistant"
    assert len(result["messages"][0].content) == 2
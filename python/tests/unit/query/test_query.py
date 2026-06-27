"""Query loop smoke tests — mirrors CurrentBackend.test.ts / LangGraphBackend.test.ts."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docker_agent.config import UserConfig
from docker_agent.query import query
from docker_agent.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from docker_agent.types.message import UserMessage


def _fake_provider(calls: list[list[object]]):
    idx = 0

    class _Provider:
        name = "fake"

        async def stream(self, _params):
            nonlocal idx
            events = calls[idx] if idx < len(calls) else []
            idx += 1
            for ev in events:
                yield ev

    return _Provider()


@pytest.mark.asyncio
async def test_query_text_only_turn(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")

    provider = _fake_provider(
        [
            [
                TextDeltaEvent(text="hello"),
                MessageStopEvent(stop_reason="end_turn"),
            ],
        ]
    )

    events = []
    with patch(
        "docker_agent.query.load_user_config",
        return_value=UserConfig(),
    ):
        async for ev in query(
            messages=[UserMessage(content="hi")],
            ctx=ctx,
            provider=provider,
        ):
            events.append(ev)

    assert any(e.type == "assistant_text" for e in events)


@pytest.mark.asyncio
async def test_query_tool_call_turn(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")

    provider = _fake_provider(
        [
            [
                ToolUseStartEvent(id="t1", name="list_stacks"),
                ToolUseDeltaEvent(id="t1", args_partial_json="{}"),
                ToolUseStopEvent(id="t1"),
                MessageStopEvent(stop_reason="tool_use"),
            ],
            [
                TextDeltaEvent(text="done"),
                MessageStopEvent(stop_reason="end_turn"),
            ],
        ]
    )

    events = []
    with patch(
        "docker_agent.query.load_user_config",
        return_value=UserConfig(),
    ):
        async for ev in query(
            messages=[UserMessage(content="list stacks")],
            ctx=ctx,
            provider=provider,
        ):
            events.append(ev)

    types = [e.type for e in events]
    assert "iteration_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "assistant_text" in types
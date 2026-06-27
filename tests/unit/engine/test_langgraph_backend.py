"""LangGraphBackend smoke test — mirrors LangGraphBackend.test.ts."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agent import BackendQueryParams
from src.config import UserConfig
from src.engine.langgraph_backend import LangGraphBackend
from src.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from src.types.message import UserMessage


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
async def test_smoke_streams_expected_events(make_loop_ctx, tmp_project) -> None:
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

    backend = LangGraphBackend()
    events = []
    with patch(
        "src.engine.langgraph_backend.load_user_config",
        return_value=UserConfig(),
    ):
        async for ev in backend.query(
            BackendQueryParams.model_construct(
                messages=[UserMessage(content="list stacks")],
                ctx=ctx,
                provider=provider,
            )
        ):
            events.append(ev)

    types = [e.type for e in events]
    assert "iteration_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "assistant_text" in types
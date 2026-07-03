"""Smoke test for the LangGraphBackend native agent harness."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from tests.unit.engine.test_langchain_backend import ToolCallingFakeModel, _run_backend


@pytest.mark.asyncio
async def test_smoke_streams_expected_events(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "list_stacks", "args": {}, "id": "call-list"}],
            ),
            AIMessage(content="done"),
        ]
    )

    events = await _run_backend(ctx, model)

    types = [getattr(e, "type", None) for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert any(getattr(e, "delta", "") == "done" for e in events)
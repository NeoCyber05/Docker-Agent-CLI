"""Query loop smoke tests — mirrors CurrentBackend.test.ts / LangGraphBackend.test.ts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from docker_agent.config import UserConfig
from docker_agent.query import query
from docker_agent.services.api.types import (
    CallModelParams,
    MessageStopEvent,
    ProviderEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from docker_agent.services.docker.compose_runner import ComposeRunner
from docker_agent.state.state_store import StateStore
from docker_agent.tool import ToolContext
from docker_agent.types.message import UserMessage


class NoopDockerEngine:
    pass


def _make_loop_ctx(tmp_project: Path) -> Any:
    base = ToolContext(
        cwd=str(tmp_project),
        state_store=StateStore(str(tmp_project / ".docker-agent")),
        docker_engine=NoopDockerEngine(),
        compose_runner=ComposeRunner(str(tmp_project)),
        abort_signal=asyncio.Event(),
    )
    ctx = type(
        "LoopContext",
        (ToolContext,),
        {
            "request_permission": AsyncMock(return_value={"kind": "approve"}),
            "request_confirm": AsyncMock(return_value={"kind": "approve"}),
            "request_typed_confirm": AsyncMock(
                return_value={"kind": "typed_confirm_value", "value": ""}
            ),
            "request_secrets_input": AsyncMock(return_value={"kind": "deny"}),
            "allow_set": set(),
            "logger": None,
        },
    )(**base.__dict__)
    ctx.allow_set = set()
    return ctx


def _fake_provider(calls: list[list[object]]) -> Any:
    idx = 0

    class _Provider:
        name = "fake"

        async def stream(self, _params: Any) -> AsyncIterator[object]:
            nonlocal idx
            events = calls[idx] if idx < len(calls) else []
            idx += 1
            for ev in events:
                yield ev

    return _Provider()


@pytest.mark.asyncio
async def test_query_text_only_turn(tmp_project: Path) -> None:
    ctx = _make_loop_ctx(tmp_project)
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
async def test_query_tool_call_turn(tmp_project: Path) -> None:
    ctx = _make_loop_ctx(tmp_project)
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


@pytest.mark.asyncio
async def test_query_does_not_expose_or_run_pull_image_tool(tmp_project: Path) -> None:
    from docker_agent.services.docker.image_validator import ImageValidationResult

    ctx = _make_loop_ctx(tmp_project)
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")

    class FakeImageValidator:
        async def validate_image(
            self, image: str, *, signal: Any | None = None
        ) -> ImageValidationResult:
            return ImageValidationResult(image=image, status="valid", source="registry")

    class FakeDockerEngine:
        def __init__(self) -> None:
            self.pulled: list[str] = []

        async def pull_image(
            self, image: str, *, signal: Any | None = None
        ) -> AsyncIterator[str]:
            self.pulled.append(image)
            yield "pulled"

    class Provider:
        name = "fake"

        def __init__(self) -> None:
            self.turn = 0
            self.tool_names_by_turn: list[list[str]] = []

        async def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]:
            self.tool_names_by_turn.append([tool.name for tool in params.tools])
            events: list[ProviderEvent]
            if self.turn == 0:
                events = [
                    ToolUseStartEvent(id="t1", name="pull_image"),
                    ToolUseDeltaEvent(
                        id="t1", args_partial_json='{"image":"nginx:1.27"}'
                    ),
                    ToolUseStopEvent(id="t1"),
                    MessageStopEvent(stop_reason="tool_use"),
                ]
            else:
                events = [
                    TextDeltaEvent(text="done"),
                    MessageStopEvent(stop_reason="end_turn"),
                ]
            self.turn += 1
            for ev in events:
                yield ev

        def list_models(self) -> None:
            return None

    engine = FakeDockerEngine()
    ctx.docker_engine = engine
    ctx.image_validator = FakeImageValidator()
    provider = Provider()

    events = []
    with patch(
        "docker_agent.query.load_user_config",
        return_value=UserConfig(),
    ):
        async for ev in query(
            messages=[UserMessage(content="deploy nginx")],
            ctx=ctx,
            provider=provider,
        ):
            events.append(ev)

    assert "pull_image" not in provider.tool_names_by_turn[0]
    assert ctx.request_permission.await_count == 0
    assert engine.pulled == []
    assert not any(
        ev.type == "tool_call" and getattr(ev, "name", None) == "pull_image"
        for ev in events
    )
    assert any(ev.type == "assistant_text" for ev in events)

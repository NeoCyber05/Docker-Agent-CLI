"""Shared fixtures for integration tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from src.query_engine import QueryEngine
from src.services.api.types import (
    MessageStopEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from src.state.state_store import StateStore
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def fake_provider(event_lists: list[list[Any]]):
    call_index = 0

    class _Provider:
        name = "fake"

        async def stream(self, _params: object) -> AsyncIterator[Any]:
            nonlocal call_index
            events = event_lists[call_index] if call_index < len(event_lists) else []
            call_index += 1
            for ev in events:
                yield ev

    return _Provider()


def plan_stack_events(input_data: object) -> list[Any]:
    return [
        ToolUseStartEvent(id="t1", name="plan_stack"),
        ToolUseDeltaEvent(id="t1", args_partial_json=json.dumps(input_data)),
        ToolUseStopEvent(id="t1"),
        MessageStopEvent(stop_reason="tool_use"),
    ]


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True)
    (tmp_path / ".docker-agent" / "policies.yaml").write_text("project: {}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def state_store(tmp_project: Path) -> StateStore:
    return StateStore(str(tmp_project / ".docker-agent"))


@pytest.fixture
def compose_runner(tmp_project: Path) -> MockComposeRunner:
    return MockComposeRunner(str(tmp_project))


@pytest.fixture
def make_engine(tmp_project: Path, state_store: StateStore, compose_runner: MockComposeRunner):
    def _make(event_lists: list[list[Any]]) -> QueryEngine:
        return QueryEngine(
            cwd=str(tmp_project),
            state_store=state_store,
            docker_engine=MockDockerEngine(),
            compose_runner=compose_runner,
            provider=fake_provider(event_lists),
            health_check_deadline_ms=0,
        )

    return _make
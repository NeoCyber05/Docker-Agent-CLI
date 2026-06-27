"""Shared helpers for LangGraph backend tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from docker_agent.services.docker.compose_runner import ComposeRunner
from docker_agent.services.docker.engine_client import create_engine_client
from docker_agent.state.state_store import StateStore
from docker_agent.tool import ToolContext


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True)
    return tmp_path


def _build_tool_ctx(tmp_project: Path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_project),
        state_store=StateStore(str(tmp_project / ".docker-agent")),
        docker_engine=create_engine_client(),
        compose_runner=ComposeRunner(str(tmp_project)),
        abort_signal=asyncio.Event(),
    )


@pytest.fixture
def make_tool_ctx(tmp_project: Path):
    def _factory() -> ToolContext:
        return _build_tool_ctx(tmp_project)

    return _factory


def _build_loop_ctx(tmp_project: Path) -> Any:
    """Return a LoopContext-like object with stub callbacks."""
    from unittest.mock import AsyncMock

    ctx = _build_tool_ctx(tmp_project)
    return type(
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
    )(**ctx.__dict__)


@pytest.fixture
def make_loop_ctx(tmp_project: Path):
    def _factory() -> Any:
        return _build_loop_ctx(tmp_project)

    return _factory


async def drain(gen: AsyncIterator[Any]) -> list[Any]:
    return [ev async for ev in gen]
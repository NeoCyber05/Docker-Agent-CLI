"""Shared fixtures/helpers for tool tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypeVar

import pytest

from docker_agent.services.docker.compose_runner import ComposeRunner
from docker_agent.services.docker.engine_client import create_engine_client
from docker_agent.state.state_store import StateStore
from docker_agent.tool import ToolContext, ToolDone

T = TypeVar("T")


async def drain_with_progress(gen: AsyncIterator[Any]) -> tuple[list[Any], Any]:
    """Collect yielded progress values and the terminal ``ToolDone`` result."""
    progress: list[Any] = []
    result: Any = None
    async for item in gen:
        if isinstance(item, ToolDone):
            result = item.result
        else:
            progress.append(item)
    return progress, result


async def drain(gen: AsyncIterator[Any]) -> Any:
    """Drain an async generator and return its final value."""
    _, result = await drain_with_progress(gen)
    return result


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    return tmp_path


def make_ctx(
    tmp_project: Path,
    *,
    docker_engine: Any = None,
    compose_runner: ComposeRunner | None = None,
) -> ToolContext:
    state_dir = tmp_project / ".docker-agent"
    state_dir.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        cwd=str(tmp_project),
        state_store=StateStore(str(state_dir)),
        docker_engine=docker_engine or create_engine_client(),
        compose_runner=compose_runner or ComposeRunner(str(tmp_project)),
        abort_signal=asyncio.Event(),
    )
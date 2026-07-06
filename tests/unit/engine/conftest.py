"""Shared helpers for LangGraph backend tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True)
    return tmp_path


def _build_loop_ctx(tmp_project: Path) -> Any:
    return SimpleNamespace(
        cwd=str(tmp_project),
        abort_signal=asyncio.Event(),
        session_id="default",
        provider_name="unknown",
        model=None,
        request_permission=AsyncMock(return_value={"kind": "approve"}),
        request_confirm=AsyncMock(return_value={"kind": "approve"}),
        request_typed_confirm=AsyncMock(return_value={"kind": "typed_confirm_value", "value": ""}),
        request_secrets_input=AsyncMock(return_value={"kind": "deny"}),
        allow_set=set(),
        logger=None,
        resources=[],
    )


@pytest.fixture
def make_tool_ctx(tmp_project: Path):
    def _factory() -> Any:
        return _build_loop_ctx(tmp_project)

    return _factory


@pytest.fixture
def make_loop_ctx(tmp_project: Path):
    def _factory() -> Any:
        return _build_loop_ctx(tmp_project)

    return _factory


async def drain(gen: AsyncIterator[Any]) -> list[Any]:
    return [ev async for ev in gen]


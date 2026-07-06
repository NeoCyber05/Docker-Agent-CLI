"""Shared helpers for provider tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest


async def drain_events(gen: AsyncIterator[Any]) -> list[Any]:
    events: list[Any] = []
    async for ev in gen:
        events.append(ev)
    return events


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch):
    def _set(**values: str):
        for k, v in values.items():
            monkeypatch.setenv(k, v)

    return _set

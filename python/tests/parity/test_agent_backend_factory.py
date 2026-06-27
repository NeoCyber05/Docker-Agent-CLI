"""Agent backend factory parity — mirrors AgentBackendFactory.test.ts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from docker_agent.backend.agent_backend import AgentBackend, BackendQueryParams, create_backend


def test_returns_langgraph_backend_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_BACKEND", raising=False)
    backend = create_backend()
    assert backend.name == "langgraph"


def test_returns_current_backend_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "current")
    backend = create_backend()
    assert backend.name == "current"


def test_returns_langgraph_backend_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "langgraph")
    backend = create_backend()
    assert backend.name == "langgraph"


def test_falls_back_to_langgraph_on_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "bogus")
    backend = create_backend()
    assert backend.name == "langgraph"


def test_agent_backend_has_name_and_query() -> None:
    class Stub:
        name = "stub"

        async def query(self, params: BackendQueryParams) -> AsyncIterator[Any]:
            yield {"type": "text_delta", "text": ""}
            del params

    assert isinstance(Stub(), AgentBackend)
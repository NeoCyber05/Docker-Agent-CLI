"""Agent backend abstraction + factory.

Parity: ``src/backend/AgentBackend.ts``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from docker_agent.types.events import LoopEvent
from docker_agent.types.message import Message


class BackendQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    messages: list[Message]
    ctx: Any  # LoopContext
    provider: Any  # Provider protocol — Any so test fakes validate
    model: str | None = None


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]: ...


def create_backend() -> AgentBackend:
    flag = os.environ.get("DOCKER_AGENT_BACKEND", "langgraph")
    if flag == "current":
        from docker_agent.backend.current_backend import CurrentBackend

        return CurrentBackend()
    from docker_agent.backend.langgraph.langgraph_backend import LangGraphBackend

    return LangGraphBackend()


__all__ = ["AgentBackend", "BackendQueryParams", "create_backend"]
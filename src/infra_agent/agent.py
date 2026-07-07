"""Agent backend abstraction + factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from infra_agent.types.events import LoopEvent
from infra_agent.types.message import Message


class BackendQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    messages: list[Message]
    ctx: Any  # LoopContext
    provider: Any  # Provider protocol; Any so test fakes validate
    model: str | None = None


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]: ...


def create_backend() -> AgentBackend:
    from infra_agent.engine.langgraph.backend import LangGraphBackend

    return LangGraphBackend()


__all__ = ["AgentBackend", "BackendQueryParams", "create_backend"]

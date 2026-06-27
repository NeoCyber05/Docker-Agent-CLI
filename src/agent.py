"""Agent backend abstraction + factory.

Parity: ``src/backend/AgentBackend.ts``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from src.query import query
from src.types.events import LoopEvent
from src.types.message import Message


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


class CurrentBackend:
    name = "current"

    async def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]:
        async for ev in query(
            messages=params.messages,
            ctx=params.ctx,
            provider=params.provider,
            model=params.model,
        ):
            yield ev


def create_backend() -> AgentBackend:
    flag = os.environ.get("DOCKER_AGENT_BACKEND", "langgraph")
    if flag == "current":
        return CurrentBackend()
    
    from src.engine.langgraph_backend import LangGraphBackend

    return LangGraphBackend()


__all__ = ["AgentBackend", "BackendQueryParams", "create_backend", "CurrentBackend"]

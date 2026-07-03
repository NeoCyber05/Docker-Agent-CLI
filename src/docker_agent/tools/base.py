"""Tool abstraction.

Parity: ``src/Tool.ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from docker_agent.services.docker.compose_runner import ComposeRunner
from docker_agent.services.docker.image_validator import ImageValidator
from docker_agent.state.state_store import StateStore


@dataclass
class ToolContext:
    """Dependencies passed to every tool call."""

    cwd: str
    state_store: StateStore
    docker_engine: Any
    compose_runner: ComposeRunner
    abort_signal: asyncio.Event
    image_validator: ImageValidator | None = None
    session_id: str | None = None
    health_check_deadline_ms: int | None = None
    provider_name: str = "unknown"
    model: str | None = None


@dataclass
class ToolProgress:
    msg: str
    type: str = field(default="progress")


@dataclass
class ToolDone:
    """Terminal sentinel yielded as the last item from tool ``call()`` generators.

    Python async generators cannot ``return <value>`` (unlike TypeScript
    ``AsyncGenerator<T, R>``), so tools yield ``ToolDone(result)`` instead.
    """

    result: Any


TInput = TypeVar("TInput", bound=BaseModel, contravariant=True)
TOutput = TypeVar("TOutput", covariant=True)


@runtime_checkable
class Tool(Protocol[TInput, TOutput]):
    """A tool exposed to the LLM (or internal)."""

    name: str
    description: str
    input_schema: type[BaseModel]
    category: str

    def needs_permission(self, input: TInput) -> bool: ...
    def call(
        self, input: TInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]: ...


def find_tool_by_name(tools: list[Tool[Any, Any]], name: str) -> Tool[Any, Any] | None:
    for tool in tools:
        if tool.name == name:
            return tool
    return None


__all__ = ["Tool", "ToolContext", "ToolDone", "ToolProgress", "find_tool_by_name"]
"""LoopContext extends ToolContext with user-permission callbacks.

Parity: ``src/loopContext.ts``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from docker_agent.services.docker.compose_runner import ComposeRunner
from docker_agent.services.docker.image_validator import ImageValidator
from docker_agent.state.logger import StructuredLogger
from docker_agent.state.state_store import StateStore
from docker_agent.types.stack import StackDiff


class PlanReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compose_yaml: str
    diff: StackDiff
    auto_generated_secrets: list[dict[str, Any]] | None = None
    config_files: list[dict[str, Any]] | None = None
    hash: str | None = None


@runtime_checkable
class LoopContext(Protocol):
    """ToolContext plus user-interaction callbacks used by the engine loop."""

    cwd: str
    state_store: StateStore
    docker_engine: Any
    compose_runner: ComposeRunner
    abort_signal: asyncio.Event
    image_validator: ImageValidator | None
    session_id: str | None
    health_check_deadline_ms: int | None
    request_permission: Any
    request_confirm: Any
    request_typed_confirm: Any
    request_secrets_input: Any
    allow_set: set[str]
    logger: StructuredLogger | None


__all__ = ["LoopContext", "PlanReadyPayload"]
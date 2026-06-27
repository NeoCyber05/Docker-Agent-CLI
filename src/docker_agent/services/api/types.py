"""Provider API types.

Parity: ``src/services/api/types.ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from docker_agent.types.message import Message


class UsageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")


class TextDeltaEvent(BaseModel):
    type: str = "text_delta"
    text: str


class ToolUseStartEvent(BaseModel):
    type: str = "tool_use_start"
    id: str
    name: str


class ToolUseDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: str = "tool_use_delta"
    id: str
    args_partial_json: str = Field(alias="argsPartialJson")


class ToolUseStopEvent(BaseModel):
    type: str = "tool_use_stop"
    id: str


class MessageStopEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: str = "message_stop"
    stop_reason: str = Field(alias="stopReason")


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: str = "usage"
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")


class ErrorEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    type: str = "error"
    error: Exception


ProviderEvent = (
    TextDeltaEvent
    | ToolUseStartEvent
    | ToolUseDeltaEvent
    | ToolUseStopEvent
    | MessageStopEvent
    | UsageEvent
    | ErrorEvent
)


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    name: str
    description: str
    input_schema: type[BaseModel]


class CallModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    messages: list[Message]
    tools: list[ToolSchema]
    system: str
    model: str | None = None
    signal: asyncio.Event | None = None


@runtime_checkable
class Provider(Protocol):
    name: str

    def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]: ...
    def list_models(self) -> Any | None: ...


__all__ = [
    "CallModelParams",
    "ErrorEvent",
    "MessageStopEvent",
    "Provider",
    "ProviderEvent",
    "TextDeltaEvent",
    "ToolSchema",
    "ToolUseDeltaEvent",
    "ToolUseStartEvent",
    "ToolUseStopEvent",
    "UsageEvent",
    "UsageInfo",
]
"""Event payloads emitted inside the Docker MCP server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["tool_call"] = "tool_call"
    name: str
    input: Any


class ToolProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["tool_progress"] = "tool_progress"
    msg: str


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["tool_result"] = "tool_result"
    name: str
    output: Any


class RollbackStarted(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["rollback_started"] = "rollback_started"
    stack_name: str = Field(alias="stackName")
    reason: str
    detail: str | None = None
    running_services: list[str] | None = Field(default=None, alias="runningServices")


class RollbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["rollback_result"] = "rollback_result"
    stack_name: str = Field(alias="stackName")
    ok: bool
    restored: str
    detail: str | None = None


__all__ = [
    "RollbackResult",
    "RollbackStarted",
    "ToolCall",
    "ToolProgress",
    "ToolResult",
]


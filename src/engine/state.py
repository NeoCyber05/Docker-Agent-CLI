"""LangGraph agent state.

Parity: ``src/backend/langgraph/state.ts``.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from src.types.message import Message


class PendingToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_use_id: str
    name: str
    input: Any
    output: Any
    is_error: bool


def _add_messages(left: list[Message], right: list[Message]) -> list[Message]:
    return left + right


def _add_results(
    left: list[PendingToolResult], right: list[PendingToolResult]
) -> list[PendingToolResult]:
    return left + right


def _overwrite(_left: Any, right: Any) -> Any:
    return right


class AgentState(BaseModel):
    """Pydantic-based state for the agent graph."""

    model_config = ConfigDict(extra="forbid")

    messages: Annotated[list[Message], _add_messages] = Field(default_factory=list)
    iter: Annotated[int, _overwrite] = 0
    allow_set: Annotated[set[str], _overwrite] = Field(default_factory=set)
    pending_tool_results: Annotated[list[PendingToolResult], _add_results] = Field(
        default_factory=list
    )
    aborted: Annotated[bool, _overwrite] = False
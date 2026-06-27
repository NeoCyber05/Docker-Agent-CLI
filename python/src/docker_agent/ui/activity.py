"""Activity feed state for the TUI.

Parity: ``src/ui/activity.ts``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypedDict

from docker_agent.types.message import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)
from docker_agent.ui.tool_presentation import present_tool, sanitize_tool_text

MAX_PROGRESS_LINES = 20
MAX_PROGRESS_BYTES = 4096
_id_counter = 0


def _next_id() -> str:
    global _id_counter
    _id_counter += 1
    return f"act-{int(time.time() * 1000):x}-{_id_counter:x}"


ToolActivityStatus = Literal["running", "completed", "failed", "cancelled"]


@dataclass
class ToolActivity:
    id: str
    type: Literal["tool"] = "tool"
    name: str = ""
    title: str = ""
    summary: str = ""
    status: ToolActivityStatus = "running"
    progress_msgs: list[str] = field(default_factory=list)
    detail_lines: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None


@dataclass
class TextActivity:
    id: str
    type: Literal["text"] = "text"
    role: Literal["user", "assistant", "error"] = "assistant"
    text: str = ""


@dataclass
class UsageActivity:
    id: str
    type: Literal["usage"] = "usage"
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RollbackActivity:
    id: str
    type: Literal["rollback"] = "rollback"
    stack_name: str = ""
    phase: Literal["started", "completed"] = "started"
    ok: bool | None = None
    restored: str | None = None
    detail: str | None = None


ActivityItem = ToolActivity | TextActivity | UsageActivity | RollbackActivity


@dataclass
class ActivityState:
    items: list[ActivityItem] = field(default_factory=list)
    active_tool_activity_id: str | None = None


def _bound_ui_lines(lines: list[str]) -> list[str]:
    bounded: list[str] = []
    for line in lines:
        bounded.extend(sanitize_tool_text(line).split("\n"))
    bounded = bounded[-MAX_PROGRESS_LINES:]
    while len("\n".join(bounded).encode("utf-8")) > MAX_PROGRESS_BYTES and bounded:
        bounded.pop(0)
    return bounded


def _output_failed(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    return (
        output.get("ok") is False
        or output.get("healthy") is False
        or (
            isinstance(output.get("exitCode"), int) and output.get("exitCode") != 0
        )
        or output.get("status") in {"error", "failed"}
    )


class ReplaceAction(TypedDict):
    type: Literal["replace"]
    items: list[ActivityItem]


class ResetAction(TypedDict):
    type: Literal["reset"]


class ToolCallAction(TypedDict):
    type: Literal["tool_call"]
    name: str
    input: Any


class ToolProgressAction(TypedDict):
    type: Literal["tool_progress"]
    msg: str


class ToolResultAction(TypedDict):
    type: Literal["tool_result"]
    name: str
    output: Any


class ToolErrorAction(TypedDict):
    type: Literal["tool_error"]
    name: str
    error: str


class ToolCancelledAction(TypedDict):
    type: Literal["tool_cancelled"]


class AssistantTextAction(TypedDict):
    type: Literal["assistant_text"]
    delta: str


class UserTextAction(TypedDict):
    type: Literal["user_text"]
    text: str


class ErrorAction(TypedDict):
    type: Literal["error"]
    error: BaseException


class UsageAction(TypedDict):
    type: Literal["usage"]
    input_tokens: int
    output_tokens: int


class RollbackStartedAction(TypedDict):
    type: Literal["rollback_started"]
    stack_name: str
    reason: str
    detail: str


class RollbackResultAction(TypedDict):
    type: Literal["rollback_result"]
    stack_name: str
    ok: bool
    restored: str
    detail: str | None


ActivityAction = (
    ReplaceAction
    | ResetAction
    | ToolCallAction
    | ToolProgressAction
    | ToolResultAction
    | ToolErrorAction
    | ToolCancelledAction
    | AssistantTextAction
    | UserTextAction
    | ErrorAction
    | UsageAction
    | RollbackStartedAction
    | RollbackResultAction
)


def activity_reducer(state: ActivityState, action: ActivityAction) -> ActivityState:
    now = time.time()
    match action["type"]:
        case "replace":
            return ActivityState(items=list(action["items"]), active_tool_activity_id=None)
        case "reset":
            return ActivityState(items=[], active_tool_activity_id=None)
        case "tool_call":
            tool_id = _next_id()
            presentation = present_tool(action["name"], action["input"])
            tool = ToolActivity(
                id=tool_id,
                name=action["name"],
                title=presentation.title,
                summary=presentation.summary,
                status="running",
                detail_lines=list(presentation.detail_lines),
                start_time=now,
            )
            return ActivityState(
                items=[*state.items, tool],
                active_tool_activity_id=tool_id,
            )
        case "tool_progress":
            active_id = state.active_tool_activity_id
            if not active_id:
                return state
            items: list[ActivityItem] = []
            for item in state.items:
                if item.type == "tool" and item.id == active_id:
                    items.append(
                        replace(
                            item,
                            progress_msgs=_bound_ui_lines([*item.progress_msgs, action["msg"]]),
                        )
                    )
                else:
                    items.append(item)
            return replace(state, items=items)
        case "tool_result":
            target_id = state.active_tool_activity_id
            if not target_id:
                return state
            presentation = present_tool(action["name"], None, action["output"])
            result_items: list[ActivityItem] = []
            for item in state.items:
                if item.type == "tool" and item.id == target_id:
                    result_items.append(
                        replace(
                            item,
                            status="failed" if _output_failed(action["output"]) else "completed",
                            detail_lines=_bound_ui_lines(
                                [*item.detail_lines, *presentation.detail_lines]
                            ),
                            end_time=now,
                        )
                    )
                else:
                    result_items.append(item)
            return ActivityState(items=result_items, active_tool_activity_id=None)
        case "tool_error":
            target_id = state.active_tool_activity_id
            if not target_id:
                return state
            error_items: list[ActivityItem] = []
            for item in state.items:
                if item.type == "tool" and item.id == target_id:
                    error_items.append(
                        replace(
                            item,
                            status="failed",
                            detail_lines=_bound_ui_lines(
                                [*item.detail_lines, f"Error: {action['error']}"]
                            ),
                            end_time=now,
                        )
                    )
                else:
                    error_items.append(item)
            return ActivityState(items=error_items, active_tool_activity_id=None)
        case "tool_cancelled":
            target_id = state.active_tool_activity_id
            if not target_id:
                return state
            cancelled_items: list[ActivityItem] = []
            for item in state.items:
                if item.type == "tool" and item.id == target_id:
                    cancelled_items.append(
                        replace(item, status="cancelled", end_time=now)
                    )
                else:
                    cancelled_items.append(item)
            return ActivityState(items=cancelled_items, active_tool_activity_id=None)
        case "assistant_text":
            last = state.items[-1] if state.items else None
            if last and last.type == "text" and last.role == "assistant":
                updated = replace(last, text=last.text + action["delta"])
                return replace(state, items=[*state.items[:-1], updated])
            return replace(
                state,
                items=[
                    *state.items,
                    TextActivity(id=_next_id(), role="assistant", text=action["delta"]),
                ],
            )
        case "user_text":
            return replace(
                state,
                items=[
                    *state.items,
                    TextActivity(id=_next_id(), role="user", text=action["text"]),
                ],
            )
        case "error":
            return replace(
                state,
                items=[
                    *state.items,
                    TextActivity(
                        id=_next_id(),
                        role="error",
                        text=str(action["error"]),
                    ),
                ],
            )
        case "usage":
            return replace(
                state,
                items=[
                    *state.items,
                    UsageActivity(
                        id=_next_id(),
                        input_tokens=action["input_tokens"],
                        output_tokens=action["output_tokens"],
                    ),
                ],
            )
        case "rollback_started":
            return replace(
                state,
                items=[
                    *state.items,
                    RollbackActivity(
                        id=_next_id(),
                        stack_name=action["stack_name"],
                        phase="started",
                        detail=action["detail"],
                    ),
                ],
            )
        case "rollback_result":
            updated_items = list(state.items)
            found = False
            for index in range(len(updated_items) - 1, -1, -1):
                item = updated_items[index]
                if (
                    item.type == "rollback"
                    and item.stack_name == action["stack_name"]
                    and item.phase == "started"
                ):
                    updated_items[index] = replace(
                        item,
                        phase="completed",
                        ok=action["ok"],
                        restored=action["restored"],
                        detail=action.get("detail"),
                    )
                    found = True
                    break
            if not found:
                updated_items.append(
                    RollbackActivity(
                        id=_next_id(),
                        stack_name=action["stack_name"],
                        phase="completed",
                        ok=action["ok"],
                        restored=action["restored"],
                        detail=action.get("detail"),
                    )
                )
            return replace(state, items=updated_items)
        case _:
            return state


def project_messages_to_activities(messages: list[Message]) -> list[ActivityItem]:
    items: list[ActivityItem] = []
    tool_map: dict[str, ToolActivity] = {}

    for msg in messages:
        if isinstance(msg, UserMessage):
            items.append(TextActivity(id=_next_id(), role="user", text=msg.content))
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                data = block.model_dump(by_alias=True)
                if data["type"] == "text":
                    last = items[-1] if items else None
                    if last and last.type == "text" and last.role == "assistant":
                        last.text += data["text"]
                    else:
                        items.append(
                            TextActivity(id=_next_id(), role="assistant", text=data["text"])
                        )
                elif data["type"] == "tool_use":
                    presentation = present_tool(data["name"], data["input"])
                    tool = ToolActivity(
                        id=data["id"],
                        name=data["name"],
                        title=presentation.title,
                        summary=presentation.summary,
                        status="running",
                        detail_lines=list(presentation.detail_lines),
                        start_time=0,
                    )
                    items.append(tool)
                    tool_map[data["id"]] = tool
        elif isinstance(msg, ToolResultMessage):
            existing = tool_map.get(msg.tool_use_id)
            try:
                parsed_output = json.loads(msg.content)
            except json.JSONDecodeError:
                parsed_output = None
            if existing:
                existing.status = (
                    "failed"
                    if msg.is_error or _output_failed(parsed_output)
                    else "completed"
                )
                if msg.is_error:
                    existing.detail_lines = _bound_ui_lines(
                        [*existing.detail_lines, f"Error: {msg.content}"]
                    )
                elif parsed_output is not None:
                    presentation = present_tool(existing.name, None, parsed_output)
                    existing.detail_lines = _bound_ui_lines(
                        [*existing.detail_lines, *presentation.detail_lines]
                    )
                else:
                    existing.detail_lines = _bound_ui_lines(
                        [*existing.detail_lines, msg.content]
                    )
            else:
                items.append(
                    ToolActivity(
                        id=msg.tool_use_id,
                        name="unknown",
                        title="Tool result",
                        summary="Orphaned tool result",
                        status=(
                            "failed"
                            if msg.is_error or _output_failed(parsed_output)
                            else "completed"
                        ),
                        detail_lines=[sanitize_tool_text(msg.content)],
                        start_time=0,
                    )
                )
    return items


__all__ = [
    "ActivityAction",
    "ActivityItem",
    "ActivityState",
    "RollbackActivity",
    "TextActivity",
    "ToolActivity",
    "ToolActivityStatus",
    "UsageActivity",
    "activity_reducer",
    "project_messages_to_activities",
]
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
from docker_agent.types.stack import StackDiff
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


PlanActivityStatus = Literal["pending", "approved", "denied"]


@dataclass
class PlanSecretRef:
    service: str
    keys: list[str]


@dataclass
class PlanConfigRef:
    path: str
    content: str
    bytes: int


@dataclass
class PlanActivity:
    id: str
    type: Literal["plan"] = "plan"
    request_id: str = ""
    compose_yaml: str = ""
    diff: StackDiff | None = None
    auto_generated_secrets: list[PlanSecretRef] = field(default_factory=list)
    config_files: list[PlanConfigRef] = field(default_factory=list)
    status: PlanActivityStatus = "pending"
    show_yaml: bool = False
    show_config: bool = False


ActivityItem = ToolActivity | TextActivity | UsageActivity | RollbackActivity | PlanActivity


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


class PlanReadyAction(TypedDict):
    type: Literal["plan_ready"]
    request_id: str
    compose_yaml: str
    diff: StackDiff
    auto_generated_secrets: list[Any] | None
    config_files: list[Any] | None


class PlanResolvedAction(TypedDict):
    type: Literal["plan_resolved"]
    request_id: str
    status: PlanActivityStatus


class PlanToggleYamlAction(TypedDict):
    type: Literal["plan_toggle_yaml"]
    request_id: str


class PlanToggleConfigAction(TypedDict):
    type: Literal["plan_toggle_config"]
    request_id: str


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
    | PlanReadyAction
    | PlanResolvedAction
    | PlanToggleYamlAction
    | PlanToggleConfigAction
)


def _plan_secret_refs(raw: list[Any] | None) -> list[PlanSecretRef]:
    if not raw:
        return []
    refs: list[PlanSecretRef] = []
    for item in raw:
        if isinstance(item, PlanSecretRef):
            refs.append(item)
        elif isinstance(item, dict):
            refs.append(
                PlanSecretRef(
                    service=str(item.get("service", "")),
                    keys=[str(key) for key in item.get("keys", [])],
                )
            )
        elif hasattr(item, "service") and hasattr(item, "keys"):
            refs.append(
                PlanSecretRef(
                    service=str(item.service),
                    keys=[str(key) for key in item.keys],
                )
            )
    return refs


def _plan_config_refs(raw: list[Any] | None) -> list[PlanConfigRef]:
    if not raw:
        return []
    refs: list[PlanConfigRef] = []
    for item in raw:
        if isinstance(item, PlanConfigRef):
            refs.append(item)
        elif isinstance(item, dict):
            refs.append(
                PlanConfigRef(
                    path=str(item.get("path", "")),
                    content=str(item.get("content", "")),
                    bytes=int(item.get("bytes", 0)),
                )
            )
        elif hasattr(item, "path") and hasattr(item, "content"):
            refs.append(
                PlanConfigRef(
                    path=str(item.path),
                    content=str(item.content),
                    bytes=int(getattr(item, "bytes", 0)),
                )
            )
    return refs


def _update_plan_activity(
    items: list[ActivityItem],
    request_id: str,
    updater: Any,
) -> list[ActivityItem]:
    updated: list[ActivityItem] = []
    for item in items:
        if item.type == "plan" and item.request_id == request_id:
            updated.append(updater(item))
        else:
            updated.append(item)
    return updated


def serialize_activity_items(items: list[ActivityItem]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in items:
        if item.type == "tool":
            serialized.append(
                {
                    "type": "tool",
                    "id": item.id,
                    "name": item.name,
                    "title": item.title,
                    "summary": item.summary,
                    "status": item.status,
                    "progressMsgs": item.progress_msgs,
                    "detailLines": item.detail_lines,
                    "startTime": item.start_time,
                    "endTime": item.end_time,
                }
            )
        elif item.type == "text":
            serialized.append(
                {
                    "type": "text",
                    "id": item.id,
                    "role": item.role,
                    "text": item.text,
                }
            )
        elif item.type == "usage":
            serialized.append(
                {
                    "type": "usage",
                    "id": item.id,
                    "inputTokens": item.input_tokens,
                    "outputTokens": item.output_tokens,
                }
            )
        elif item.type == "rollback":
            serialized.append(
                {
                    "type": "rollback",
                    "id": item.id,
                    "stackName": item.stack_name,
                    "phase": item.phase,
                    "ok": item.ok,
                    "restored": item.restored,
                    "detail": item.detail,
                }
            )
        elif item.type == "plan":
            serialized.append(
                {
                    "type": "plan",
                    "id": item.id,
                    "requestId": item.request_id,
                    "composeYaml": item.compose_yaml,
                    "diff": item.diff.model_dump(by_alias=True) if item.diff else None,
                    "autoGeneratedSecrets": [
                        {"service": secret.service, "keys": list(secret.keys)}
                        for secret in item.auto_generated_secrets
                    ],
                    "configFiles": [
                        {
                            "path": config.path,
                            "content": config.content,
                            "bytes": config.bytes,
                        }
                        for config in item.config_files
                    ],
                    "status": item.status,
                    "showYaml": item.show_yaml,
                    "showConfig": item.show_config,
                }
            )
    return serialized


def deserialize_activity_items(raw: list[Any]) -> list[ActivityItem]:
    items: list[ActivityItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item_type = entry.get("type")
        if item_type == "tool":
            items.append(
                ToolActivity(
                    id=str(entry.get("id", _next_id())),
                    name=str(entry.get("name", "")),
                    title=str(entry.get("title", "")),
                    summary=str(entry.get("summary", "")),
                    status=entry.get("status", "completed"),
                    progress_msgs=list(entry.get("progressMsgs", [])),
                    detail_lines=list(entry.get("detailLines", [])),
                    start_time=float(entry.get("startTime", 0)),
                    end_time=entry.get("endTime"),
                )
            )
        elif item_type == "text":
            items.append(
                TextActivity(
                    id=str(entry.get("id", _next_id())),
                    role=entry.get("role", "assistant"),
                    text=str(entry.get("text", "")),
                )
            )
        elif item_type == "usage":
            items.append(
                UsageActivity(
                    id=str(entry.get("id", _next_id())),
                    input_tokens=int(entry.get("inputTokens", 0)),
                    output_tokens=int(entry.get("outputTokens", 0)),
                )
            )
        elif item_type == "rollback":
            items.append(
                RollbackActivity(
                    id=str(entry.get("id", _next_id())),
                    stack_name=str(entry.get("stackName", "")),
                    phase=entry.get("phase", "started"),
                    ok=entry.get("ok"),
                    restored=entry.get("restored"),
                    detail=entry.get("detail"),
                )
            )
        elif item_type == "plan":
            diff_raw = entry.get("diff")
            diff = StackDiff.model_validate(diff_raw) if diff_raw else None
            items.append(
                PlanActivity(
                    id=str(entry.get("id", _next_id())),
                    request_id=str(entry.get("requestId", "")),
                    compose_yaml=str(entry.get("composeYaml", "")),
                    diff=diff,
                    auto_generated_secrets=_plan_secret_refs(
                        entry.get("autoGeneratedSecrets")
                    ),
                    config_files=_plan_config_refs(entry.get("configFiles")),
                    status=entry.get("status", "approved"),
                    show_yaml=bool(entry.get("showYaml")),
                    show_config=bool(entry.get("showConfig")),
                )
            )
    return items


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
        case "plan_ready":
            return replace(
                state,
                items=[
                    *state.items,
                    PlanActivity(
                        id=_next_id(),
                        request_id=action["request_id"],
                        compose_yaml=action["compose_yaml"],
                        diff=action["diff"],
                        auto_generated_secrets=_plan_secret_refs(
                            action.get("auto_generated_secrets")
                        ),
                        config_files=_plan_config_refs(action.get("config_files")),
                        status="pending",
                    ),
                ],
            )
        case "plan_resolved":
            return replace(
                state,
                items=_update_plan_activity(
                    state.items,
                    action["request_id"],
                    lambda item: replace(item, status=action["status"]),
                ),
            )
        case "plan_toggle_yaml":
            return replace(
                state,
                items=_update_plan_activity(
                    state.items,
                    action["request_id"],
                    lambda item: replace(item, show_yaml=not item.show_yaml),
                ),
            )
        case "plan_toggle_config":
            return replace(
                state,
                items=_update_plan_activity(
                    state.items,
                    action["request_id"],
                    lambda item: replace(item, show_config=not item.show_config),
                ),
            )
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
    "PlanActivity",
    "PlanActivityStatus",
    "PlanConfigRef",
    "PlanSecretRef",
    "RollbackActivity",
    "TextActivity",
    "ToolActivity",
    "ToolActivityStatus",
    "UsageActivity",
    "activity_reducer",
    "deserialize_activity_items",
    "project_messages_to_activities",
    "serialize_activity_items",
]
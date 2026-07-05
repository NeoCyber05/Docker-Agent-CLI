"""Generic confirmation handling for MCP PendingAction payloads."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, create_model

from docker_agent.types.events import ToolCall, ToolResult
from docker_agent.types.permissions import permission_kind, permission_value

_INJECTED_TOOL_ARGS = {"cwd", "session_id", "provider_name", "model"}


def _coerce_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        for item in value:
            payload = _coerce_payload(item)
            if payload is not None:
                return payload
        return None
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return _coerce_payload(value["text"])
        return value
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return _coerce_payload(text)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def is_pending_confirmation(value: Any) -> bool:
    payload = _coerce_payload(value)
    return bool(
        payload
        and payload.get("status") == "pending_confirmation"
        and isinstance(payload.get("pending_action"), dict)
    )


def _find_confirm_tool(tools_by_name: dict[str, Any]) -> Any:
    exact = tools_by_name.get("docker.confirm_action")
    if exact is not None:
        return exact
    for name, tool in tools_by_name.items():
        if name.endswith(".confirm_action"):
            return tool
    raise RuntimeError("MCP pending confirmation requires a confirm_action tool")


async def _decision_for_pending(action: dict[str, Any], ctx: Any) -> dict[str, Any]:
    kind = action.get("kind")
    display = action.get("display") if isinstance(action.get("display"), dict) else {}
    if kind == "plan_review":
        response = await ctx.request_confirm(display)
        return {"decision": "approve" if permission_kind(response) == "approve" else "deny"}
    if kind == "typed":
        phrase = str(display.get("phrase") or action.get("phrase") or "")
        reason = str(display.get("reason") or action.get("reason") or "")
        response = await ctx.request_typed_confirm(phrase, reason)
        approved = (
            permission_kind(response) == "typed_confirm_value"
            and permission_value(response) == phrase
        )
        return {
            "decision": "approve" if approved else "deny",
            "typed_phrase": permission_value(response) if approved else None,
        }
    if kind == "secrets_input":
        service = str(display.get("service") or "")
        keys = list(display.get("keys") or [])
        reason = str(display.get("reason") or "")
        response = await ctx.request_secrets_input(service, keys, reason)
        if permission_kind(response) != "secrets_input_values":
            return {"decision": "deny"}
        values = response.get("values", {}) if isinstance(response, dict) else response.values
        return {"decision": "approve", "secrets": values}
    if kind == "permission":
        tool = str(action.get("tool") or "")
        response = await ctx.request_permission(tool, display)
        return {
            "decision": (
                "deny" if permission_kind(response) == "deny" else "approve"
            )
        }
    return {"decision": "deny"}


async def handle_pending_confirmation(
    value: Any,
    *,
    tools_by_name: dict[str, Any],
    ctx: Any,
) -> Any:
    payload = _coerce_payload(value)
    if not payload or not is_pending_confirmation(payload):
        return value

    action = payload["pending_action"]
    decision = await _decision_for_pending(action, ctx)
    confirm_tool = _find_confirm_tool(tools_by_name)
    confirm_input = {
        "pending_action_id": action["id"],
        "session_id": getattr(ctx, "session_id", None) or action.get("session_id"),
        "cwd": getattr(ctx, "cwd", None) or action.get("cwd"),
        "decision": decision.get("decision", "deny"),
        "typed_phrase": decision.get("typed_phrase"),
        "secrets": decision.get("secrets"),
    }
    return await confirm_tool.ainvoke(confirm_input)


def _filtered_args_schema(tool: BaseTool) -> type[BaseModel] | None:
    schema = getattr(tool, "args_schema", None)
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        return schema
    fields: dict[str, tuple[Any, Any]] = {}
    for name, field in schema.model_fields.items():
        if name in _INJECTED_TOOL_ARGS:
            continue
        fields[name] = (field.annotation, field)
    return create_model(
        f"{schema.__name__}RuntimeArgs",
        __config__=ConfigDict(extra="forbid", populate_by_name=True),
        **fields,
    )


def _runtime_args(ctx: Any) -> dict[str, Any]:
    return {
        "cwd": getattr(ctx, "cwd", ""),
        "session_id": getattr(ctx, "session_id", None) or "default",
        "provider_name": getattr(ctx, "provider_name", "mcp"),
        "model": getattr(ctx, "model", None),
    }


def wrap_mcp_tools_for_confirmation(
    tools: Sequence[BaseTool],
    *,
    ctx: Any,
    emit: Callable[[Any], None],
) -> list[BaseTool]:
    tools_by_name = {tool.name: tool for tool in tools}
    wrapped: list[BaseTool] = []
    for tool in tools:
        if (
            tool.name.endswith(".confirm_action")
            or tool.name.endswith(".capabilities")
            or tool.name.endswith(".summarize_context")
        ):
            continue

        async def coroutine(_tool: BaseTool = tool, **kwargs: Any) -> Any:
            call_input = {**kwargs, **_runtime_args(ctx)}
            emit(ToolCall(name=_tool.name, input=kwargs))
            result = await _tool.ainvoke(call_input)
            result = await handle_pending_confirmation(
                result,
                tools_by_name=tools_by_name,
                ctx=ctx,
            )
            emit(ToolResult(name=_tool.name, output=result))
            return result

        wrapped.append(
            StructuredTool.from_function(
                coroutine=coroutine,
                name=tool.name,
                description=tool.description,
                args_schema=_filtered_args_schema(tool),
                metadata=tool.metadata,
            )
        )
    return wrapped


__all__ = [
    "handle_pending_confirmation",
    "is_pending_confirmation",
    "wrap_mcp_tools_for_confirmation",
]


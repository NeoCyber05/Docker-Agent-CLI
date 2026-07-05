"""Normalize MCP plugin metadata for the LangGraph control plane."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docker_agent.mcp.commands import CommandSpec

_INTERNAL_TOOL_SUFFIXES = (
    ".capabilities",
    ".summarize_context",
    ".commit_action",
    ".confirm_action",
    ".rollback_action",
)
_INTERNAL_OPERATIONS = {"internal", "context", "commit", "confirm", "rollback"}


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


def _capability_items(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    items = capabilities.get("tools") if isinstance(capabilities, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _capability_by_name(capabilities: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for item in _capability_items(capabilities):
        name = item.get("name")
        if isinstance(name, str):
            by_name[name] = item
    return by_name


def is_internal_mcp_tool_name(name: str) -> bool:
    return name.endswith(_INTERNAL_TOOL_SUFFIXES)


def model_visible_mcp_tools(
    tools: Sequence[Any],
    *,
    capabilities: dict[str, Any],
) -> list[Any]:
    by_name = _capability_by_name(capabilities)
    visible: list[Any] = []
    for tool in tools:
        name = str(getattr(tool, "name", ""))
        metadata = by_name.get(name, {})
        operation = str(metadata.get("operation") or metadata.get("kind") or "")
        if is_internal_mcp_tool_name(name):
            continue
        if metadata.get("model_visible") is False:
            continue
        if operation in _INTERNAL_OPERATIONS:
            continue
        visible.append(tool)
    return visible


def mcp_high_risk_tool_names(
    tools: Sequence[Any],
    capabilities: dict[str, Any] | None = None,
) -> set[str]:
    by_name = _capability_by_name(capabilities or {})
    high_risk: set[str] = set()
    for tool in tools:
        name = str(getattr(tool, "name", ""))
        metadata = getattr(tool, "metadata", None) or {}
        cap_metadata = by_name.get(name, {})
        if (
            metadata.get("risk") == "high"
            or metadata.get("mutating") is True
            or cap_metadata.get("risk") == "high"
            or cap_metadata.get("mutating") is True
        ):
            high_risk.add(name)
    return high_risk


async def load_mcp_capabilities(tools: Sequence[Any]) -> dict[str, Any]:
    for tool in tools:
        if getattr(tool, "name", "") == "docker.capabilities" or str(
            getattr(tool, "name", "")
        ).endswith(".capabilities"):
            payload = _coerce_payload(await tool.ainvoke({}))
            return payload or {}
    return {}


def mcp_command_specs(capabilities: dict[str, Any]) -> list[CommandSpec]:
    commands = capabilities.get("commands")
    if not isinstance(commands, list):
        return []
    specs: list[CommandSpec] = []
    for command in commands:
        if isinstance(command, dict):
            specs.append(CommandSpec.model_validate(command))
    return specs


def _namespace_for_tool(tool_name: str) -> str:
    return tool_name.split(".", 1)[0] if "." in tool_name else tool_name


def mcp_commit_tool_name(
    pending_action: dict[str, Any],
    capabilities: dict[str, Any],
) -> str:
    tool_name = str(pending_action.get("tool") or "")
    metadata = _capability_by_name(capabilities).get(tool_name, {})
    configured = metadata.get("commit_tool")
    if isinstance(configured, str) and configured:
        return configured
    namespace = _namespace_for_tool(tool_name)
    return f"{namespace}.commit_action"


def mcp_rollback_tool_name(
    deploy_result: dict[str, Any],
    capabilities: dict[str, Any],
) -> str:
    rollback_action = deploy_result.get("rollback_action")
    if isinstance(rollback_action, dict):
        tool = rollback_action.get("tool")
        if isinstance(tool, str) and tool:
            return tool
    for metadata in _capability_items(capabilities):
        configured = metadata.get("rollback_tool")
        if isinstance(configured, str) and configured:
            return configured
    return "rollback_action"


async def mcp_context_summary(
    tools: Sequence[Any],
    *,
    capabilities: dict[str, Any],
    cwd: str,
    fallback: str,
) -> str:
    context = capabilities.get("context") if isinstance(capabilities, dict) else None
    summarize_tool = context.get("summarize_tool") if isinstance(context, dict) else None
    if not summarize_tool:
        return fallback
    for tool in tools:
        if getattr(tool, "name", "") == summarize_tool:
            payload = _coerce_payload(await tool.ainvoke({"cwd": cwd}))
            if payload and isinstance(payload.get("summary"), str):
                return str(payload["summary"])
            return fallback
    return fallback


__all__ = [
    "is_internal_mcp_tool_name",
    "load_mcp_capabilities",
    "mcp_command_specs",
    "mcp_commit_tool_name",
    "mcp_context_summary",
    "mcp_high_risk_tool_names",
    "mcp_rollback_tool_name",
    "model_visible_mcp_tools",
]
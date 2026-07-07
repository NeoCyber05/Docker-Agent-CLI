"""Normalize MCP plugin metadata for the LangGraph control plane."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from infra_agent.mcp.commands import CommandSpec

_INTERNAL_TOOL_SUFFIXES = (
    ".capabilities",
    ".summarize_context",
    ".list_resources",
    ".commit_action",
    ".rollback_action",
)
_INTERNAL_OPERATIONS = {"internal", "context", "resource", "commit", "rollback"}


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


def _namespace_for_tool(tool_name: str) -> str:
    return tool_name.split(".", 1)[0] if "." in tool_name else tool_name


def _namespace_for_payload(tool_name: str, payload: dict[str, Any]) -> str:
    namespace = payload.get("namespace")
    if isinstance(namespace, str) and namespace:
        return namespace
    plugin = payload.get("plugin")
    if isinstance(plugin, dict) and isinstance(plugin.get("namespace"), str):
        return str(plugin["namespace"])
    return _namespace_for_tool(tool_name)


def _normal_context(namespace: str, payload: dict[str, Any]) -> dict[str, list[str]]:
    context = payload.get("context") if isinstance(payload, dict) else None
    summarize_tools: list[str] = []
    list_resources_tools: list[str] = []
    if isinstance(context, dict):
        summarize_tool = context.get("summarize_tool")
        if isinstance(summarize_tool, str) and summarize_tool:
            summarize_tools.append(summarize_tool)
        summarize_list = context.get("summarize_tools")
        if isinstance(summarize_list, list):
            summarize_tools.extend(
                item for item in summarize_list if isinstance(item, str) and item
            )
        list_resource_tool = context.get("list_resources_tool")
        if isinstance(list_resource_tool, str) and list_resource_tool:
            list_resources_tools.append(list_resource_tool)
        list_resource_list = context.get("list_resources_tools")
        if isinstance(list_resource_list, list):
            list_resources_tools.extend(
                item for item in list_resource_list if isinstance(item, str) and item
            )
    return {
        "summarize_tools": list(dict.fromkeys(summarize_tools)),
        "list_resources_tools": list(dict.fromkeys(list_resources_tools)),
    }


def _merge_context(target: dict[str, list[str]], addition: dict[str, list[str]]) -> None:
    for key in ("summarize_tools", "list_resources_tools"):
        for name in addition.get(key, []):
            if name not in target[key]:
                target[key].append(name)


def _normalize_tool_metadata(namespace: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    name = normalized.get("name")
    if not isinstance(name, str) or "." not in name:
        raise ValueError("MCP capability tool names must be namespaced")
    operation = normalized.get("operation") or normalized.get("kind")
    if operation == "pending_action":
        normalized.setdefault("commit_tool", f"{namespace}.commit_action")
        normalized.setdefault("rollback_tool", f"{namespace}.rollback_action")
    return normalized


def _ensure_registry_shape(capabilities: dict[str, Any]) -> dict[str, Any]:
    if "plugins" in capabilities:
        context = capabilities.setdefault("context", {})
        if isinstance(context, dict):
            context.setdefault("summarize_tools", [])
            context.setdefault("list_resources_tools", [])
        capabilities.setdefault("instructions", [])
        return capabilities
    namespace = capabilities.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        tools = _capability_items(capabilities)
        first_name = str(tools[0].get("name", "")) if tools else ""
        namespace = _namespace_for_tool(first_name) if first_name else "default"
    context = _normal_context(namespace, capabilities)
    instructions: list[dict[str, str]] = []
    raw_instructions = capabilities.get("instructions")
    if isinstance(raw_instructions, str) and raw_instructions.strip():
        instructions.append({"namespace": namespace, "instructions": raw_instructions})
    return {
        "plugins": {namespace: capabilities},
        "tools": [
            _normalize_tool_metadata(namespace, item) for item in _capability_items(capabilities)
        ],
        "commands": capabilities.get("commands")
        if isinstance(capabilities.get("commands"), list)
        else [],
        "context": context,
        "instructions": instructions,
    }


def is_internal_mcp_tool_name(name: str) -> bool:
    return name.endswith(_INTERNAL_TOOL_SUFFIXES)


def model_visible_mcp_tools(
    tools: Sequence[Any],
    *,
    capabilities: dict[str, Any],
) -> list[Any]:
    registry = _ensure_registry_shape(capabilities)
    by_name = _capability_by_name(registry)
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
    registry = _ensure_registry_shape(capabilities or {})
    by_name = _capability_by_name(registry)
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
    plugins: dict[str, dict[str, Any]] = {}
    merged_tools: list[dict[str, Any]] = []
    merged_commands: list[dict[str, Any]] = []
    merged_context: dict[str, list[str]] = {"summarize_tools": [], "list_resources_tools": []}
    merged_instructions: list[dict[str, str]] = []
    seen_tool_names: set[str] = set()

    for tool in tools:
        tool_name = str(getattr(tool, "name", ""))
        if not tool_name.endswith(".capabilities"):
            continue
        payload = _coerce_payload(await tool.ainvoke({})) or {}
        namespace = _namespace_for_payload(tool_name, payload)
        if not namespace or "." in namespace:
            raise ValueError("MCP capability namespace must be a single non-empty segment")
        if namespace in plugins:
            raise ValueError(f"Duplicate MCP capability namespace: {namespace}")
        plugins[namespace] = payload

        for item in _capability_items(payload):
            normalized = _normalize_tool_metadata(namespace, item)
            name = str(normalized["name"])
            if name in seen_tool_names:
                raise ValueError(f"Duplicate MCP tool capability: {name}")
            seen_tool_names.add(name)
            merged_tools.append(normalized)

        commands = payload.get("commands")
        if isinstance(commands, list):
            merged_commands.extend(command for command in commands if isinstance(command, dict))
        _merge_context(merged_context, _normal_context(namespace, payload))
        instructions = payload.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            merged_instructions.append({"namespace": namespace, "instructions": instructions})

    return {
        "plugins": plugins,
        "tools": merged_tools,
        "commands": merged_commands,
        "context": merged_context,
        "instructions": merged_instructions,
    }


def mcp_command_specs(capabilities: dict[str, Any]) -> list[CommandSpec]:
    registry = _ensure_registry_shape(capabilities)
    commands = registry.get("commands")
    if not isinstance(commands, list):
        return []
    specs: list[CommandSpec] = []
    for command in commands:
        if isinstance(command, dict):
            specs.append(CommandSpec.model_validate(command))
    return specs


def mcp_plugin_instructions(capabilities: dict[str, Any]) -> str:
    """Compose domain-specific system-prompt guidance from connected plugins.

    Each plugin contributes an ``instructions`` string via its capabilities. The
    core prompt stays domain-agnostic and only the guidance for plugins that are
    actually connected is injected, so adding a new infrastructure plugin (k8s,
    cloud, ...) requires no change to the core prompt.
    """
    registry = _ensure_registry_shape(capabilities)
    entries = registry.get("instructions")
    if not isinstance(entries, list):
        return ""
    blocks: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = entry.get("instructions")
        if isinstance(text, str) and text.strip():
            blocks.append(text.strip())
    return "\n\n".join(blocks)


def mcp_commit_tool_name(
    pending_action: dict[str, Any],
    capabilities: dict[str, Any],
) -> str:
    registry = _ensure_registry_shape(capabilities)
    tool_name = str(pending_action.get("tool") or "")
    metadata = _capability_by_name(registry).get(tool_name, {})
    configured = metadata.get("commit_tool")
    if isinstance(configured, str) and configured:
        return configured
    # Internal pending actions may omit namespace (e.g. initialize_project_policy).
    # In that case prefer a known commit tool from capabilities instead of
    # synthesizing "<tool>.commit_action", which is not a real MCP tool.
    if "." not in tool_name:
        for item in _capability_items(registry):
            name = item.get("name")
            if isinstance(name, str) and name.endswith(".commit_action"):
                return name
        return "docker.commit_action"
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
    registry = _ensure_registry_shape(capabilities)
    action_tool = deploy_result.get("tool")
    if isinstance(action_tool, str):
        metadata = _capability_by_name(registry).get(action_tool, {})
        configured = metadata.get("rollback_tool")
        if isinstance(configured, str) and configured:
            return configured
        return f"{_namespace_for_tool(action_tool)}.rollback_action"
    for metadata in _capability_items(registry):
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
    registry = _ensure_registry_shape(capabilities)
    context = registry.get("context") if isinstance(registry, dict) else None
    summarize_tools = context.get("summarize_tools") if isinstance(context, dict) else None
    if not isinstance(summarize_tools, list) or not summarize_tools:
        return fallback
    by_name = {str(getattr(tool, "name", "")): tool for tool in tools}
    summaries: list[str] = []
    for name in summarize_tools:
        if not isinstance(name, str):
            continue
        tool = by_name.get(name)
        if tool is None:
            continue
        payload = _coerce_payload(await tool.ainvoke({"cwd": cwd}))
        summary = payload.get("summary") if isinstance(payload, dict) else None
        if isinstance(summary, str) and summary.strip():
            summaries.append(summary.strip())
    return "\n\n".join(summaries) if summaries else fallback


async def mcp_list_resources(
    tools: Sequence[Any],
    *,
    capabilities: dict[str, Any],
    cwd: str,
) -> list[dict[str, Any]]:
    registry = _ensure_registry_shape(capabilities)
    context = registry.get("context") if isinstance(registry, dict) else None
    resource_tools = context.get("list_resources_tools") if isinstance(context, dict) else None
    if not isinstance(resource_tools, list) or not resource_tools:
        return []
    by_name = {str(getattr(tool, "name", "")): tool for tool in tools}
    resources: list[dict[str, Any]] = []
    for name in resource_tools:
        if not isinstance(name, str):
            continue
        tool = by_name.get(name)
        if tool is None:
            continue
        payload = _coerce_payload(await tool.ainvoke({"cwd": cwd}))
        if not isinstance(payload, dict):
            continue
        items = payload.get("resources")
        if isinstance(items, list):
            resources.extend(item for item in items if isinstance(item, dict))
    return resources


__all__ = [
    "is_internal_mcp_tool_name",
    "load_mcp_capabilities",
    "mcp_command_specs",
    "mcp_commit_tool_name",
    "mcp_context_summary",
    "mcp_high_risk_tool_names",
    "mcp_list_resources",
    "mcp_rollback_tool_name",
    "model_visible_mcp_tools",
]

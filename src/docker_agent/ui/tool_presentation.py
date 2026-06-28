"""Tool presentation helpers for the activity feed.

Parity: ``src/ui/toolPresentation.ts``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

SECRET_PATTERN = re.compile(r"secret|token|password|apiKey|credential", re.IGNORECASE)
MAX_DETAIL_LINES = 20
MAX_DETAIL_BYTES = 4096


@dataclass
class ToolPresentation:
    title: str
    summary: str
    detail_lines: list[str]


def _tool_input_as_dict(input_data: Any) -> dict[str, Any]:
    """Normalize tool input for presentation (dict or pydantic model)."""
    if input_data is None:
        return {}
    if isinstance(input_data, dict):
        return input_data
    if isinstance(input_data, BaseModel):
        return input_data.model_dump(by_alias=True, exclude_none=True)
    return {}


def _mask_secrets(text: str) -> str:
    masked = re.sub(
        r"((?:--)?(?:secret|token|password|api[-_]?key|credential)[\w-]*(?:=|[ \t]+))"
        r'["\']?[^\s,"\'}\]]+["\']?',
        r"\1***",
        text,
        flags=re.IGNORECASE,
    )
    lines: list[str] = []
    for line in masked.split("\n"):
        if not SECRET_PATTERN.search(line):
            lines.append(line)
            continue
        lines.append(
            re.sub(
                r'(["\']?(?:secret|token|password|apiKey|credential)[\w]*["\']?\s*[:=]\s*)'
                r'["\']?[^\s,"\'}\]]+["\']?',
                r'\1"***"',
                line,
                flags=re.IGNORECASE,
            )
        )
    return "\n".join(lines)


def _sanitize_argv(args: list[str]) -> list[str]:
    mask_next = False
    sanitized: list[str] = []
    for arg in args:
        if mask_next:
            mask_next = False
            sanitized.append("***")
            continue
        if re.match(r"^--?(?:secret|token|password|api[-_]?key|credential)(?:=|$)", arg, re.I):
            if "=" not in arg:
                mask_next = True
                sanitized.append(arg)
            else:
                idx = arg.index("=")
                sanitized.append(f"{arg[: idx + 1]}***")
            continue
        sanitized.append(arg)
    return sanitized


def _truncate_lines(lines: list[str], max_lines: int, max_bytes: int) -> list[str]:
    trimmed = lines[:max_lines]
    text = "\n".join(trimmed)
    while len(text.encode("utf-8")) > max_bytes and trimmed:
        trimmed = trimmed[:-1]
        text = "\n".join(trimmed)
    if len(text.encode("utf-8")) > max_bytes and trimmed:
        last_index = len(trimmed) - 1
        last = trimmed[last_index]
        prefix = "\n".join(trimmed[:-1])
        budget = max_bytes - len(prefix.encode("utf-8"))
        while len(last.encode("utf-8")) > budget and last:
            last = last[:-1]
        trimmed[last_index] = f"{last}…"
    return trimmed


def to_detail_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line for line in value.split("\n") if line]
    if not isinstance(value, dict):
        return [str(value)]
    lines: list[str] = []
    for key, item in value.items():
        if item is None:
            continue
        if SECRET_PATTERN.search(key):
            lines.append(f"{key}: ***")
            continue
        if isinstance(item, str):
            parts = item.split("\n")
            if len(parts) == 1:
                lines.append(f"{key}: {item}")
            else:
                lines.append(f"{key}:")
                for part in parts[:10]:
                    lines.append(f"  {part}")
                if len(parts) > 10:
                    lines.append(f"  … ({len(parts) - 10} more lines)")
        elif isinstance(item, list):
            lines.append(f"{key}: [{len(item)} items]")
            values = (
                _sanitize_argv(item)
                if key == "args" and all(isinstance(v, str) for v in item)
                else item
            )
            for entry in values[:5]:
                for detail in to_detail_lines(entry)[:3]:
                    lines.append(f"  {detail}")
            if len(item) > 5:
                lines.append(f"  … ({len(item) - 5} more items)")
        elif isinstance(item, dict):
            lines.append(f"{key}:")
            nested = to_detail_lines(item)
            for nested_line in nested[:5]:
                lines.append(f"  {nested_line}")
            if len(nested) > 5:
                lines.append("  …")
        else:
            lines.append(f"{key}: {item}")
    return lines


def sanitize_tool_text(text: str) -> str:
    masked = _mask_secrets(text)
    if len(masked.encode("utf-8")) <= MAX_DETAIL_BYTES:
        return masked
    ellipsis = "…"
    truncated = masked
    while len(truncated.encode("utf-8")) + len(ellipsis.encode("utf-8")) > MAX_DETAIL_BYTES:
        truncated = truncated[:-1]
    return truncated + ellipsis


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


def _format_bullet_list(items: list[str], *, max_items: int = 10) -> list[str]:
    lines = [f"  • {item}" for item in items[:max_items]]
    if len(items) > max_items:
        lines.append(f"  … and {len(items) - max_items} more")
    return lines


def _permission_detail_remove_container(input_dict: dict[str, Any]) -> list[str]:
    containers = input_dict.get("containers", [])
    if not isinstance(containers, list):
        containers = [str(containers)]
    stop_only = input_dict.get("stopOnly") is True
    force = input_dict.get("force", True) is not False

    if stop_only:
        header = f"Will stop {len(containers)} orphan Docker container(s) (not removed):"
        command = "docker stop"
    elif force:
        header = f"Will force-remove {len(containers)} orphan Docker container(s):"
        command = "docker rm -f"
    else:
        header = f"Will stop and remove {len(containers)} orphan Docker container(s):"
        command = "docker stop && docker rm"

    lines = [
        header,
        "Only removes the containers listed below (not all stopped containers).",
        f"Command: {command}",
        *_format_bullet_list(containers),
    ]
    if len(containers) >= 3:
        lines.append("Typed confirmation required for 3+ containers.")
    return lines


def _permission_detail_destroy_stack(input_dict: dict[str, Any]) -> list[str]:
    stack_name = input_dict.get("stackName", "unknown")
    remove_volumes = input_dict.get("removeVolumes") is True
    lines = [
        f'Will tear down stack "{stack_name}"',
        "Command: docker compose down",
        "Containers and networks for this stack will be stopped and removed.",
    ]
    if remove_volumes:
        lines.append("All volumes for this stack will be DELETED.")
    else:
        lines.append("Named volumes are kept.")
    return lines


def _permission_detail_destroy_all_stacks(input_dict: dict[str, Any]) -> list[str]:
    remove_volumes = input_dict.get("removeVolumes") is True
    lines = [
        "Will tear down ALL stacks managed by docker-agent",
        "Command: docker compose down (each tracked stack)",
    ]
    if remove_volumes:
        lines.append("All volumes for every stack will be DELETED.")
    else:
        lines.append("Named volumes are kept.")
    return lines


def _build_detail(input_data: Any, output: Any | None = None) -> list[str]:
    input_lines = to_detail_lines(input_data)
    output_lines = to_detail_lines(output) if output is not None else []
    lines: list[str] = []
    if input_lines:
        lines.extend(["Input:", *[f"  {line}" for line in input_lines]])
    if output_lines:
        lines.extend(["Output:", *[f"  {line}" for line in output_lines]])
    return lines


def _finalize_presentation(
    title: str,
    summary: str,
    detail_lines: list[str],
    output: Any | None = None,
) -> ToolPresentation:
    lines = list(detail_lines)
    if output is not None:
        lines.extend(_build_detail(None, output))
    trimmed = _truncate_lines(lines, MAX_DETAIL_LINES, MAX_DETAIL_BYTES)
    return ToolPresentation(
        title=sanitize_tool_text(title),
        summary=sanitize_tool_text(summary),
        detail_lines=[sanitize_tool_text(line) for line in trimmed],
    )


def present_tool(name: str, input_data: Any = None, output: Any = None) -> ToolPresentation:
    title = f"Tool: {name}"
    summary = f"Run {name}"

    input_dict = _tool_input_as_dict(input_data)

    if name == "initialize_project_policy" and input_dict:
        content = str(input_dict.get("content", ""))
        detail_lines = [
            f"Reason: {input_dict.get('reason', '')}",
            f"Path: {input_dict.get('path', '')}",
            "",
            "Proposed Content:",
            *[f"  {line}" for line in content.split("\n")],
        ]
        return ToolPresentation(
            title="Initialize Project Policy",
            summary=(
                "Create project-policies.yaml with default/empty configuration "
                "(respecting global policy)"
            ),
            detail_lines=[sanitize_tool_text(line) for line in detail_lines],
        )

    if name == "plan_stack":
        stack_name = input_dict.get("stackName", "unknown")
        intent = input_dict.get("intent", "")
        title = f"Plan stack: {stack_name}"
        summary = f"Generate Compose plan for {stack_name}{f' ({intent})' if intent else ''}"
    elif name == "apply_stack":
        stack_name = input_dict.get("stackName", "unknown")
        title = f"Apply stack: {stack_name}"
        summary = f"Deploy stack {stack_name}"
    elif name == "destroy_stack":
        stack_name = input_dict.get("stackName", "unknown")
        remove_volumes = input_dict.get("removeVolumes") is True
        title = f"Destroy stack: {stack_name}"
        summary = f"Tear down stack {stack_name}{' (volumes removed)' if remove_volumes else ''}"
        detail_lines = _permission_detail_destroy_stack(input_dict)
        return _finalize_presentation(title, summary, detail_lines, output)
    elif name == "stop_stack":
        stack_name = input_dict.get("stackName", "unknown")
        services = input_dict.get("services")
        if isinstance(services, list) and services:
            service_label = ", ".join(str(service) for service in services)
            title = f"Stop stack: {stack_name}"
            summary = f"Stop service(s) {service_label} in {stack_name} (containers kept)"
        else:
            title = f"Stop stack: {stack_name}"
            summary = f"Stop all services in {stack_name} (containers kept)"
        detail_lines = [
            f"Stack: {stack_name}",
            "Action: docker compose stop (containers are not removed)",
        ]
        if isinstance(services, list) and services:
            detail_lines.append(f"Services: {', '.join(str(service) for service in services)}")
        return _finalize_presentation(title, summary, detail_lines, output)
    elif name == "destroy_all_stacks":
        title = "Destroy all stacks"
        summary = "Tear down all stacks"
        detail_lines = _permission_detail_destroy_all_stacks(input_dict)
        return _finalize_presentation(title, summary, detail_lines, output)
    elif name == "remove_container":
        containers = input_dict.get("containers", [])
        stop_only = input_dict.get("stopOnly") is True
        action = "Stop" if stop_only else "Remove"
        container_list = ", ".join(containers) if isinstance(containers, list) else str(containers)
        title = f"{action} container: {container_list}"
        summary = f"{action} Docker container(s): {container_list}"
        detail_lines = _permission_detail_remove_container(input_dict)
        return _finalize_presentation(title, summary, detail_lines, output)
    elif name == "list_stacks":
        title = "List stacks"
        summary = "List all stacks"
    elif name == "inspect_drift":
        stack_name = input_dict.get("stackName", "unknown")
        title = f"Inspect drift: {stack_name}"
        summary = f"Compare desired vs actual for {stack_name}"
    elif name == "remediate_drift":
        stack_name = input_dict.get("stackName", "unknown")
        title = f"Remediate drift: {stack_name}"
        summary = f"Detect drift and prepare remediation for {stack_name}"
    elif name == "get_stack_status":
        stack_name = input_dict.get("stackName", "unknown")
        title = f"Stack status: {stack_name}"
        summary = f"Container state and logs for {stack_name}"
    elif name == "get_logs":
        stack_name = input_dict.get("stackName", "unknown")
        service = input_dict.get("service")
        title = f"Logs: {stack_name}/{service}" if service else f"Logs: {stack_name}"
        summary = f"Fetch logs for {stack_name}{f' (service: {service})' if service else ''}"
    elif name == "get_health":
        stack_name = input_dict.get("stackName", "unknown")
        title = f"Health: {stack_name}"
        summary = f"Per-container health and stats for {stack_name}"
    elif name == "pull_image":
        image = input_dict.get("image", "unknown")
        title = f"Pull image: {image}"
        summary = f"Validate and pull {image}"
    elif name == "exec_docker":
        args = input_dict.get("args")
        cmd = " ".join(_sanitize_argv(args)) if isinstance(args, list) else ""
        title = f"Docker: {cmd}"
        summary = f"Run docker {cmd}"
        detail_lines = [sanitize_tool_text(f"$ docker {cmd}")]
        return ToolPresentation(
            title=sanitize_tool_text(title),
            summary=sanitize_tool_text(summary),
            detail_lines=detail_lines,
        )

    detail_lines = _truncate_lines(
        _build_detail(input_dict, output), MAX_DETAIL_LINES, MAX_DETAIL_BYTES
    )
    return ToolPresentation(
        title=sanitize_tool_text(title),
        summary=sanitize_tool_text(summary),
        detail_lines=[sanitize_tool_text(line) for line in detail_lines],
    )


def safe_json_value(value: Any) -> str:
    return sanitize_tool_text(json.dumps(value, default=str))


__all__ = [
    "ToolPresentation",
    "present_tool",
    "safe_json_value",
    "sanitize_tool_text",
    "to_detail_lines",
]
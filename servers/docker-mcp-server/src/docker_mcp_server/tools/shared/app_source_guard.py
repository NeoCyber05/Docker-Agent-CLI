"""Validate that custom services have application source for script entrypoints."""

from __future__ import annotations

import re
from dataclasses import dataclass

from docker_mcp_server.types.stack import ServiceSpec

_SCRIPT_EXTENSIONS = (".js", ".mjs", ".ts", ".py", ".rb", ".php", ".jar")
_SCRIPT_EXTENSION_PATTERN = "|".join(re.escape(ext) for ext in _SCRIPT_EXTENSIONS)
_ENTRYPOINT_PATTERN = re.compile(
    rf"(?:^|[\s/])([\w.\-]+(?:{_SCRIPT_EXTENSION_PATTERN}))(?:\s|$)"
)


@dataclass
class AppSourceIssue:
    service: str
    entrypoint: str
    message: str


def _command_text(spec: ServiceSpec) -> str:
    command = spec.command
    if command is None:
        return ""
    if isinstance(command, str):
        return command
    return " ".join(command)


def check_app_source_artifacts(
    services: dict[str, ServiceSpec],
    staged_config_paths: set[str],
) -> list[AppSourceIssue]:
    """Block services that run a script without a bind mount or staged config file."""
    issues: list[AppSourceIssue] = []
    for name, spec in services.items():
        text = _command_text(spec)
        if not text:
            continue
        match = _ENTRYPOINT_PATTERN.search(text)
        if match is None:
            continue
        entrypoint = match.group(1)
        if _has_source_for_entrypoint(spec, staged_config_paths, entrypoint):
            continue
        issues.append(
            AppSourceIssue(
                service=name,
                entrypoint=entrypoint,
                message=(
                    f"custom service runs {entrypoint} but no matching bind mount or "
                    "config file was provided"
                ),
            )
        )
    return issues


def _has_source_for_entrypoint(
    spec: ServiceSpec,
    staged_config_paths: set[str],
    entrypoint: str,
) -> bool:
    target_names = {entrypoint, f"/{entrypoint}"}
    for bind in spec.volumes or []:
        parts = bind.split(":", 1)
        if len(parts) != 2:
            continue
        host, container = parts
        del host
        if container.rstrip("/").endswith(tuple(target_names)):
            return True
    return any(path.endswith(entrypoint) for path in staged_config_paths)

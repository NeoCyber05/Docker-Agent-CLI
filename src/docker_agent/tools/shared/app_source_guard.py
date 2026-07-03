"""Validate that custom services have application source for script entrypoints."""

from __future__ import annotations

import re
from dataclasses import dataclass

from docker_agent.types.stack import ServiceSpec

_SCRIPT_EXTENSIONS = (".js", ".mjs", ".ts", ".py", ".rb", ".php", ".jar")
_ENTRYPOINT_PATTERN = re.compile(
    r"(?:^|[\s/])([\w.\-]+(?:%s))(?:\s|$)"
    % "|".join(re.escape(ext) for ext in _SCRIPT_EXTENSIONS)
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
        match = _ENTRYPOINT_PATTERN.search(text)
        if not match:
            continue
        entrypoint = match.group(1)
        mounted_targets = [
            parts[1]
            for mount in (spec.volumes or [])
            if len(parts := mount.split(":")) >= 2
        ]
        covered = any(entrypoint in target for target in mounted_targets)
        provided = any(entrypoint in path for path in staged_config_paths)
        if covered or provided:
            continue
        issues.append(
            AppSourceIssue(
                service=name,
                entrypoint=entrypoint,
                message=(
                    f"service '{name}' runs '{text.strip()}' but no application "
                    f"source for '{entrypoint}' was provided via configFiles or a "
                    "bind mount. Ask the user for the source, or provide the file "
                    "content via configFiles, before planning this service."
                ),
            )
        )
    return issues


__all__ = ["AppSourceIssue", "check_app_source_artifacts"]

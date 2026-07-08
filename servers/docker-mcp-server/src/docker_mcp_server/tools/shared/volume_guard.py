"""Bind-mount safety checks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docker_mcp_server.tools.shared.spec_schemas import DraftServiceSpec

SENSITIVE_HOST_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/etc\b"),
    re.compile(r"^/proc\b"),
    re.compile(r"^/sys\b"),
    re.compile(r"^/boot\b"),
    re.compile(r"^/var/run/docker\.sock$"),
    re.compile(r"^/dev\b"),
    re.compile(r"^/root\b"),
)


@dataclass
class VolumeIssue:
    code: str
    service: str
    volume: str
    message: str


def check_volume_safety(
    cwd: str | os.PathLike[str],
    services: dict[str, DraftServiceSpec],
) -> list[VolumeIssue]:
    """Detect path traversal and sensitive host bind mounts."""
    issues: list[VolumeIssue] = []
    home = Path.home()
    cwd_path = Path(cwd)

    for svc_name, spec in services.items():
        for vol in spec.volumes or []:
            host_part = vol.split(":")[0]
            if not host_part:
                continue

            expanded = (
                str(home / host_part[2:])
                if host_part.startswith("~/")
                else host_part
            )
            resolved = (
                Path(expanded)
                if Path(expanded).is_absolute()
                else (cwd_path / expanded).resolve()
            )

            if str(resolved).startswith(str(home / ".ssh")):
                issues.append(
                    VolumeIssue(
                        code="sensitive_host_path",
                        service=svc_name,
                        volume=vol,
                        message=(
                            f"bind mount '{vol}' targets ~/.ssh Ã¢â‚¬â€ "
                            "refusing to expose SSH keys to a container"
                        ),
                    )
                )
                continue

            matched_sensitive = False
            for pattern in SENSITIVE_HOST_PATHS:
                if pattern.search(expanded):
                    issues.append(
                        VolumeIssue(
                            code="sensitive_host_path",
                            service=svc_name,
                            volume=vol,
                            message=(
                                f"bind mount '{vol}' targets sensitive host path "
                                f"'{expanded}'"
                            ),
                        )
                    )
                    matched_sensitive = True
                    break
            if matched_sensitive:
                continue

            if not Path(expanded).is_absolute():
                try:
                    relative_to_cwd = resolved.relative_to(cwd_path.resolve())
                    if str(relative_to_cwd).startswith(".."):
                        issues.append(
                            VolumeIssue(
                                code="path_traversal",
                                service=svc_name,
                                volume=vol,
                                message=(
                                    f"bind mount '{vol}' resolves outside the project "
                                    f"directory ({resolved})"
                                ),
                            )
                        )
                except ValueError:
                    issues.append(
                        VolumeIssue(
                            code="path_traversal",
                            service=svc_name,
                            volume=vol,
                            message=(
                                f"bind mount '{vol}' resolves outside the project "
                                f"directory ({resolved})"
                            ),
                        )
                    )

    return issues


def _is_named_volume_mount(volume: str) -> bool:
    """Return True when the left side of a mount string is a named volume."""
    host_part = volume.split(":")[0]
    if not host_part:
        return False
    return not host_part.startswith((".", "~", "/"))


def check_volume_references(
    services: dict[str, DraftServiceSpec],
    volumes: dict[str, Any] | None = None,
) -> list[VolumeIssue]:
    """Report services referencing named volumes not declared at top level."""
    declared = set(volumes.keys()) if volumes else set()
    issues: list[VolumeIssue] = []

    for svc_name, spec in services.items():
        for vol in spec.volumes or []:
            if not _is_named_volume_mount(vol):
                continue
            volume_name = vol.split(":")[0]
            if volume_name not in declared:
                issues.append(
                    VolumeIssue(
                        code="undeclared_volume",
                        service=svc_name,
                        volume=vol,
                        message=(
                            f"service '{svc_name}' references volume '{volume_name}' "
                            "which is not declared in top-level volumes"
                        ),
                    )
                )
    return issues


__all__ = [
    "SENSITIVE_HOST_PATHS",
    "VolumeIssue",
    "check_volume_references",
    "check_volume_safety",
]

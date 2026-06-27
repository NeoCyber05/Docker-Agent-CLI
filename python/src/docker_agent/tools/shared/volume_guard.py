"""Bind-mount safety checks.

Parity: ``src/tools/shared/volumeGuard.ts``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from docker_agent.tools.shared.spec_schemas import DraftServiceSpec

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
                            f"bind mount '{vol}' targets ~/.ssh — "
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


__all__ = [
    "SENSITIVE_HOST_PATHS",
    "VolumeIssue",
    "check_volume_safety",
]
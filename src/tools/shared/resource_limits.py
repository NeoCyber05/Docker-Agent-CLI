"""Stack resource and port limit checks.

Parity: ``src/tools/shared/resourceLimits.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tools.shared.spec_schemas import DraftServiceSpec

MAX_SERVICES_PER_STACK = 25
VALID_PORT_RANGE = {"min": 1, "max": 65535}
PRIVILEGED_PORT_THRESHOLD = 1024


@dataclass
class ResourceLimitIssue:
    code: str
    path: str
    message: str


def _extract_host_port(value: str) -> int | None:
    trimmed = value.strip()
    slash = trimmed.rfind("/")
    body = trimmed[:slash] if slash >= 0 else trimmed
    parts = body.split(":")
    if len(parts) == 1:
        return None
    host_segment = parts[0] if len(parts) == 2 else parts[-2]
    match = re.match(r"^(\d+)$", host_segment)
    if not match:
        return None
    return int(match.group(1))


def check_resource_limits(
    services: dict[str, DraftServiceSpec],
) -> list[ResourceLimitIssue]:
    """Check service count and host port ranges."""
    issues: list[ResourceLimitIssue] = []
    names = list(services.keys())
    if len(names) > MAX_SERVICES_PER_STACK:
        issues.append(
            ResourceLimitIssue(
                code="too_many_services",
                path="services",
                message=(
                    f"stack has {len(names)} services; "
                    f"maximum is {MAX_SERVICES_PER_STACK}"
                ),
            )
        )

    for svc_name, spec in services.items():
        for index, port_value in enumerate(spec.ports or []):
            host_port = _extract_host_port(port_value)
            if host_port is None:
                continue
            path = f"services.{svc_name}.ports[{index}]"
            if (
                host_port < VALID_PORT_RANGE["min"]
                or host_port > VALID_PORT_RANGE["max"]
            ):
                issues.append(
                    ResourceLimitIssue(
                        code="invalid_port",
                        path=path,
                        message=(
                            f"host port {host_port} is outside valid range "
                            f"{VALID_PORT_RANGE['min']}-{VALID_PORT_RANGE['max']}"
                        ),
                    )
                )
                continue
            if host_port < PRIVILEGED_PORT_THRESHOLD:
                issues.append(
                    ResourceLimitIssue(
                        code="privileged_port",
                        path=path,
                        message=(
                            f"host port {host_port} is privileged "
                            f"(< {PRIVILEGED_PORT_THRESHOLD}); "
                            f"use a port >= {PRIVILEGED_PORT_THRESHOLD}"
                        ),
                    )
                )
    return issues


__all__ = [
    "MAX_SERVICES_PER_STACK",
    "PRIVILEGED_PORT_THRESHOLD",
    "VALID_PORT_RANGE",
    "ResourceLimitIssue",
    "check_resource_limits",
]
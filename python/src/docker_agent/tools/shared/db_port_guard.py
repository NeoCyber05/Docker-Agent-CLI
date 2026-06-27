"""Database default port exposure guard.

Parity: ``src/tools/shared/dbPortGuard.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docker_agent.tools.shared.spec_schemas import DraftServiceSpec


@dataclass(frozen=True)
class DbPortEntry:
    image_pattern: re.Pattern[str]
    container_ports: list[int]
    label: str


DB_PORT_MAP: list[DbPortEntry] = [
    DbPortEntry(re.compile(r"^postgres(:|$)"), [5432], "postgres"),
    DbPortEntry(re.compile(r"^mysql(:|$)"), [3306], "mysql"),
    DbPortEntry(re.compile(r"^mariadb(:|$)"), [3306], "mariadb"),
    DbPortEntry(re.compile(r"^mongo(:|$)"), [27017], "mongo"),
    DbPortEntry(re.compile(r"^redis(:|$)"), [6379], "redis"),
]


@dataclass
class DbPortExposureIssue:
    service: str
    image: str
    container_port: int
    host_port: int
    message: str


def _parse_host_and_container_port(value: str) -> dict[str, int] | None:
    trimmed = value.strip()
    slash = trimmed.rfind("/")
    body = trimmed[:slash] if slash >= 0 else trimmed
    parts = body.split(":")
    if len(parts) < 2:
        return None
    host_str = parts[0] if len(parts) == 2 else parts[-2]
    container_str = parts[-1]
    host_match = re.match(r"^(\d+)$", host_str)
    container_match = re.match(r"^(\d+)$", container_str)
    if not host_match or not container_match:
        return None
    return {
        "host_port": int(host_match.group(1)),
        "container_port": int(container_match.group(1)),
    }


def check_db_port_exposure(
    services: dict[str, DraftServiceSpec],
) -> list[DbPortExposureIssue]:
    """Block publishing DB default container port to the same host port."""
    issues: list[DbPortExposureIssue] = []
    for svc_name, spec in services.items():
        entry = next(
            (e for e in DB_PORT_MAP if e.image_pattern.search(spec.image)),
            None,
        )
        if entry is None:
            continue
        for port_value in spec.ports or []:
            parsed = _parse_host_and_container_port(port_value)
            if parsed is None:
                continue
            if parsed["host_port"] in entry.container_ports:
                issues.append(
                    DbPortExposureIssue(
                        service=svc_name,
                        image=spec.image,
                        container_port=parsed["container_port"],
                        host_port=parsed["host_port"],
                        message=(
                            f"database {entry.label} default port {parsed['host_port']} "
                            f"is published to host port {parsed['host_port']}; "
                            "remove the port mapping or use a non-default container port "
                            "— the service is reachable from other compose services "
                            "without publishing"
                        ),
                    )
                )
    return issues


__all__ = [
    "DB_PORT_MAP",
    "DbPortEntry",
    "DbPortExposureIssue",
    "check_db_port_exposure",
]
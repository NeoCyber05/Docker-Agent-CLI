"""Undeclared network reference guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docker_mcp_server.tools.shared.spec_schemas import DraftServiceSpec


@dataclass
class NetworkIssue:
    code: str
    service: str
    network: str
    message: str


def check_network_references(
    services: dict[str, DraftServiceSpec],
    networks: dict[str, Any] | None = None,
) -> list[NetworkIssue]:
    """Report services referencing networks not declared at top level."""
    declared = set(networks.keys()) if networks else set()
    issues: list[NetworkIssue] = []

    for svc_name, spec in services.items():
        for net in spec.networks or []:
            if net not in declared:
                issues.append(
                    NetworkIssue(
                        code="undeclared_network",
                        service=svc_name,
                        network=net,
                        message=(
                            f"service '{svc_name}' references network '{net}' "
                            "which is not declared in top-level networks"
                        ),
                    )
                )
    return issues


__all__ = ["NetworkIssue", "check_network_references"]

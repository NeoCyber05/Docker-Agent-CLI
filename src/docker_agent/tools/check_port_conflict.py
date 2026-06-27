"""check_port_conflict tool.

Parity: ``src/tools/checkPortConflict.ts``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from docker_agent.tool import ToolContext, ToolDone, ToolProgress
from docker_agent.tools.shared.spec_schemas import (
    HybridServiceIntent,
    StackDraft,
    format_validation_error,
)
from docker_agent.tools.shared.translator import prepare_stack_draft
from docker_agent.types.stack import ServiceSpec


@dataclass(frozen=True)
class PublishedPort:
    host_ip: str
    host_port: int
    container_port: int
    protocol: Literal["tcp", "udp"]


@dataclass
class PortConflict:
    source: Literal["draft", "running"]
    service: str
    host_ip: str
    host_port: int
    protocol: Literal["tcp", "udp"]
    conflicts_with: str


@dataclass
class CheckPortConflictResult:
    ok: bool
    conflicts: list[PortConflict] = field(default_factory=list)
    invalid: list[dict[str, str]] = field(default_factory=list)
    docker_error: dict[str, str] | None = None


class _CheckPortConflictInput(BaseModel):
    stack_name: str | None = Field(default=None, alias="stackName")
    intent: str | None = None
    services: list[HybridServiceIntent]


def _parse_protocol(value: str) -> tuple[str, Literal["tcp", "udp"]]:
    slash = value.rfind("/")
    if slash >= 0:
        proto = value[slash + 1 :].lower()
        if proto in ("tcp", "udp"):
            return value[:slash], proto  # type: ignore[return-value]
    return value, "tcp"


def _expand_range(segment: str) -> list[int] | None:
    match = re.fullmatch(r"(\d+)-(\d+)", segment)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if start > end:
        return None
    return list(range(start, end + 1))


def _parse_port_segment(segment: str) -> list[int] | dict[str, str]:
    expanded = _expand_range(segment)
    if expanded is not None:
        return expanded
    if re.fullmatch(r"\d+", segment):
        return [int(segment)]
    return {"error": f'invalid port segment "{segment}"'}


def parse_published_ports(value: str) -> list[PublishedPort]:
    """Parse a compose port mapping into published host/container bindings."""
    body, protocol = _parse_protocol(value.strip())
    parts = body.split(":")

    if len(parts) == 1:
        return []

    host_ip = "0.0.0.0"
    if len(parts) == 2:
        host_segment = parts[0]
        container_segment = parts[1]
    else:
        container_segment = parts[-1]
        host_segment = parts[-2]
        host_ip = ":".join(parts[:-2]).strip("[]")

    host_ports = _parse_port_segment(host_segment)
    container_ports = _parse_port_segment(container_segment)
    if isinstance(host_ports, dict) or isinstance(container_ports, dict):
        return []
    if len(host_ports) != len(container_ports):
        return []

    return [
        PublishedPort(
            host_ip=host_ip or "0.0.0.0",
            host_port=host_port,
            container_port=container_ports[index],
            protocol=protocol,
        )
        for index, host_port in enumerate(host_ports)
    ]


def _normalize_host_ip(host_ip: str) -> str:
    trimmed = host_ip.strip()
    if not trimmed or trimmed in ("0.0.0.0", "::"):
        return "0.0.0.0"
    return trimmed


def _bindings_conflict(a: PublishedPort, b: PublishedPort) -> bool:
    if a.protocol != b.protocol or a.host_port != b.host_port:
        return False
    a_ip = _normalize_host_ip(a.host_ip)
    b_ip = _normalize_host_ip(b.host_ip)
    return a_ip == "0.0.0.0" or b_ip == "0.0.0.0" or a_ip == b_ip


def _describe_docker_error(error: BaseException | object) -> dict[str, str]:
    code = ""
    if hasattr(error, "code"):
        code = str(error.code)
    if code in ("ENOENT", "ECONNREFUSED"):
        return {
            "code": "docker_engine_unavailable",
            "message": (
                "Docker Engine is unavailable. Start Docker Desktop or the Docker "
                "daemon, then retry."
            ),
        }
    detail = str(error)
    return {
        "code": "docker_inspection_failed",
        "message": f"Could not inspect running Docker containers: {detail}",
    }


async def check_port_conflicts(
    stack_name: str,
    services: dict[str, ServiceSpec],
    ctx: ToolContext,
) -> CheckPortConflictResult:
    """Check draft ports for internal conflicts and running-container collisions."""
    conflicts: list[PortConflict] = []
    invalid: list[dict[str, str]] = []
    draft_bindings: list[tuple[str, PublishedPort]] = []

    for service, spec in services.items():
        for port_value in spec.ports or []:
            parsed = parse_published_ports(port_value)
            if len(parsed) == 0 and ":" in port_value:
                body, _ = _parse_protocol(port_value.strip())
                parts = body.split(":")
                if len(parts) >= 2:
                    host_segment = parts[0] if len(parts) == 2 else parts[-2]
                    container_segment = parts[-1]
                    host_ports = _parse_port_segment(host_segment)
                    container_ports = _parse_port_segment(container_segment)
                    if (
                        isinstance(host_ports, dict)
                        or isinstance(container_ports, dict)
                        or (
                            isinstance(host_ports, list)
                            and isinstance(container_ports, list)
                            and len(host_ports) != len(container_ports)
                        )
                    ) and not re.fullmatch(r"\d+", port_value.strip()):
                        invalid.append(
                            {
                                "service": service,
                                "value": port_value,
                                "message": (
                                    "host and container port ranges must have "
                                    "equal length"
                                ),
                            }
                        )
                        continue
            for binding in parsed:
                draft_bindings.append((service, binding))

    for i, (left_service, left_binding) in enumerate(draft_bindings):
        for right_service, right_binding in draft_bindings[i + 1 :]:
            if _bindings_conflict(left_binding, right_binding):
                conflicts.append(
                    PortConflict(
                        source="draft",
                        service=left_service,
                        host_ip=left_binding.host_ip,
                        host_port=left_binding.host_port,
                        protocol=left_binding.protocol,
                        conflicts_with=right_service,
                    )
                )

    running_bindings: list[tuple[str, PublishedPort]] = []

    try:
        containers = await ctx.docker_engine.list_containers(all=True)
        for summary in containers:
            if summary.state in ("exited", "dead"):
                continue
            if (
                stack_name
                and summary.labels.get("com.docker.compose.project") == stack_name
            ):
                continue
            inspected = await ctx.docker_engine.inspect(summary.id)
            ports = inspected.network_settings.ports
            for container_port_key, bindings in ports.items():
                if not bindings:
                    continue
                container_port_raw, protocol_raw = container_port_key.split("/")
                protocol: Literal["tcp", "udp"] = (
                    "udp" if protocol_raw == "udp" else "tcp"
                )
                container_port = int(container_port_raw)
                for binding in bindings:
                    host_port = binding.get("HostPort")
                    if not host_port:
                        continue
                    running_bindings.append(
                        (
                            summary.names[0] if summary.names else summary.id,
                            PublishedPort(
                                host_ip=binding.get("HostIp") or "0.0.0.0",
                                host_port=int(host_port),
                                container_port=container_port,
                                protocol=protocol,
                            ),
                        )
                    )
    except Exception as error:
        return CheckPortConflictResult(
            ok=False,
            conflicts=conflicts,
            invalid=invalid,
            docker_error=_describe_docker_error(error),
        )

    for draft_service, draft_binding in draft_bindings:
        for running_container, running_binding in running_bindings:
            if _bindings_conflict(draft_binding, running_binding):
                conflicts.append(
                    PortConflict(
                        source="running",
                        service=draft_service,
                        host_ip=draft_binding.host_ip,
                        host_port=draft_binding.host_port,
                        protocol=draft_binding.protocol,
                        conflicts_with=running_container,
                    )
                )

    conflicts.sort(
        key=lambda item: (
            item.service,
            item.host_port,
            item.protocol,
            item.source,
        )
    )

    return CheckPortConflictResult(
        ok=len(conflicts) == 0 and len(invalid) == 0,
        conflicts=conflicts,
        invalid=invalid,
    )


class _CheckPortConflictTool:
    name = "check_port_conflict"
    description = (
        "Check draft published ports for internal conflicts and collisions with "
        "running Docker containers."
    )
    input_schema = _CheckPortConflictInput
    category = "read-only"

    def needs_permission(self, _input: Any) -> bool:
        return False

    async def call(
        self, input: _CheckPortConflictInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg="Checking published ports...")
        try:
            draft = StackDraft.model_validate(
                {
                    "stackName": input.stack_name or "validate-temp-stack",
                    "intent": input.intent or "validation only",
                    "services": input.services,
                }
            )
        except ValidationError as err:
            yield ToolDone(
                CheckPortConflictResult(
                    ok=False,
                    conflicts=[],
                    invalid=[
                        {
                            "service": "*",
                            "value": "services",
                            "message": format_validation_error(err),
                        }
                    ],
                )
            )
            return
        prep = await prepare_stack_draft(draft, ctx)
        if not prep.ok:
            yield ToolDone(
                CheckPortConflictResult(
                    ok=False,
                    conflicts=[],
                    invalid=[
                        {
                            "service": "*",
                            "value": "services",
                            "message": prep.error or "unknown",
                        }
                    ],
                )
            )
            return
        assert prep.prepared is not None
        yield ToolDone(
            await check_port_conflicts(
                draft.stack_name, prep.prepared.services, ctx
            )
        )


check_port_conflict = _CheckPortConflictTool()

__all__ = [
    "CheckPortConflictResult",
    "PortConflict",
    "PublishedPort",
    "check_port_conflict",
    "check_port_conflicts",
    "parse_published_ports",
]
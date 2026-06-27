"""Stack draft translator — intent to prepared compose spec.

Parity: ``src/tools/shared/translator.ts``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from docker_agent.tool import ToolContext
from docker_agent.tools.shared.db_healthcheck import inject_db_healthchecks
from docker_agent.tools.shared.spec_schemas import (
    NetworkIntent,
    StackDraft,
    VolumeIntent,
    VolumeMount,
)
from docker_agent.types.stack import (
    DeployResources,
    DeployResourcesLimits,
    DeploySpec,
    HealthcheckSpec,
    LoggingSpec,
    ServiceSpec,
)

CATALOG_REGISTRY: dict[str, dict[str, Any]] = {
    "postgresql:16": {
        "image": "postgres:16-alpine",
        "container_port": 5432,
        "default_env": {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "POSTGRES_PASSWORD",
        },
        "default_db_volume": "/var/lib/postgresql/data",
    },
    "postgresql:15": {
        "image": "postgres:15-alpine",
        "container_port": 5432,
        "default_env": {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "POSTGRES_PASSWORD",
        },
        "default_db_volume": "/var/lib/postgresql/data",
    },
    "redis:7": {
        "image": "redis:7-alpine",
        "container_port": 6379,
        "default_env": {},
        "default_db_volume": "/data",
    },
    "redis:6": {
        "image": "redis:6-alpine",
        "container_port": 6379,
        "default_env": {},
        "default_db_volume": "/data",
    },
    "mysql:8.0": {
        "image": "mysql:8.0",
        "container_port": 3306,
        "default_env": {"MYSQL_ROOT_PASSWORD": "MYSQL_ROOT_PASSWORD"},
        "default_db_volume": "/var/lib/mysql",
    },
    "mongodb:6.0": {
        "image": "mongo:6.0",
        "container_port": 27017,
        "default_env": {},
        "default_db_volume": "/data/db",
    },
    "nginx:1.27": {
        "image": "nginx:1.27-alpine",
        "container_port": 80,
        "default_env": {},
        "healthcheck": HealthcheckSpec.model_validate(
            {
                "test": ["CMD-SHELL", "curl -f http://localhost/ || exit 1"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
            }
        ),
        "default_db_volume": "/usr/share/nginx/html",
    },
}

RESOURCE_LIMITS_MAP: dict[str, dict[str, str]] = {
    "small": {"cpus": "0.5", "memory": "512m"},
    "medium": {"cpus": "1.0", "memory": "1Gi"},
    "large": {"cpus": "2.0", "memory": "2Gi"},
}

DEFAULT_LOGGING = LoggingSpec.model_validate(
    {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }
)


@dataclass
class PreparedStack:
    stack_name: str
    intent: str
    services: dict[str, ServiceSpec]
    networks: dict[str, Any]
    volumes: dict[str, Any]
    hash: str
    config_files: dict[str, str] | None = None


@dataclass
class PrepareResult:
    ok: bool
    prepared: PreparedStack | None = None
    error: str | None = None
    issues: list[Any] | None = field(default=None)


def extract_host_port(value: str) -> int | None:
    """Parse host port from compose short port syntax."""
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


async def get_occupied_ports(ctx: ToolContext, exclude_stack: str) -> set[int]:
    """Gather host ports from other stacks and running containers."""
    occupied: set[int] = set()

    for summary in ctx.state_store.list():
        if summary.name == exclude_stack:
            continue
        definition = ctx.state_store.read(summary.name)
        if definition is None:
            continue
        for spec in definition.services.values():
            for port_val in spec.ports or []:
                host_port = extract_host_port(port_val)
                if host_port is not None:
                    occupied.add(host_port)

    try:
        containers = await ctx.docker_engine.list_containers(all=True)
    except Exception:
        return occupied

    for container in containers:
        if container.state in ("exited", "dead"):
            continue
        labels = container.labels or {}
        if labels.get("com.docker.compose.project") == exclude_stack:
            continue
        try:
            inspected = await ctx.docker_engine.inspect(container.id)
        except Exception:
            continue
        ports = inspected.network_settings.ports
        for bindings in ports.values():
            if not bindings:
                continue
            for binding in bindings:
                host_port = binding.host_port
                if host_port:
                    occupied.add(int(host_port))

    return occupied


def _service_spec_to_dict(spec: ServiceSpec) -> dict[str, Any]:
    return spec.model_dump(by_alias=True, exclude_none=True)


def calculate_canonical_hash(stack: PreparedStack) -> str:
    """SHA-256 of sorted canonical JSON representation."""
    canonical_obj = {
        "stackName": stack.stack_name,
        "intent": stack.intent,
        "services": {
            key: _service_spec_to_dict(stack.services[key])
            for key in sorted(stack.services.keys())
        },
        "networks": {key: stack.networks[key] for key in sorted(stack.networks.keys())},
        "volumes": {key: stack.volumes[key] for key in sorted(stack.volumes.keys())},
    }
    payload = json.dumps(canonical_obj, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _network_intent_to_compose(net: NetworkIntent) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if net.external:
        result["external"] = True
    if net.driver is not None:
        result["driver"] = net.driver
    if net.internal is not None:
        result["internal"] = net.internal
    if net.labels:
        result["labels"] = net.labels
    return result


def _volume_intent_to_compose(vol: VolumeIntent) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if vol.external:
        result["external"] = True
    if vol.driver is not None:
        result["driver"] = vol.driver
    if vol.driver_opts:
        result["driver_opts"] = vol.driver_opts
    if vol.labels:
        result["labels"] = vol.labels
    return result


def _volume_mount_to_compose_string(mount: VolumeMount) -> str:
    result = f"{mount.volume}:{mount.target}"
    if mount.read_only:
        result += ":ro"
    return result


def _append_volume(spec: ServiceSpec, mount: str) -> None:
    spec.volumes = list(spec.volumes or [])
    spec.volumes.append(mount)


async def prepare_stack_draft(input: StackDraft, ctx: ToolContext) -> PrepareResult:
    """Translate a validated stack draft into a prepared compose specification."""
    services: dict[str, ServiceSpec] = {}
    volumes: dict[str, Any] = {}
    networks: dict[str, Any] = {}
    default_network_name = "default"
    networks[default_network_name] = (
        {"name": input.network_name} if input.network_name else {}
    )

    for net_intent in input.networks or []:
        networks[net_intent.name] = _network_intent_to_compose(net_intent)

    for vol_intent in input.volumes or []:
        volumes[vol_intent.name] = _volume_intent_to_compose(vol_intent)

    occupied_ports = await get_occupied_ports(ctx, input.stack_name)
    previous_def = ctx.state_store.read(input.stack_name)
    next_auto_port = 8000

    for intent in input.services:
        service_name = intent.name
        service_networks = (
            intent.networks if intent.networks else [default_network_name]
        )
        spec = ServiceSpec(
            image="",
            environment=dict(intent.environment or {}),
            networks=service_networks,
            logging=DEFAULT_LOGGING,
        )

        if intent.depends_on:
            spec.depends_on = intent.depends_on
        if intent.command is not None:
            spec.command = intent.command
        if intent.scale is not None:
            spec.scale = intent.scale
        if intent.config_mounts:
            for mount in intent.config_mounts:
                _append_volume(spec, f"{mount.host_path}:{mount.container_path}")

        if intent.kind == "catalog":
            catalog_entry = CATALOG_REGISTRY.get(intent.catalog_id or "")
            if not catalog_entry:
                return PrepareResult(
                    ok=False,
                    error=f"Catalog entry not found for catalogId: {intent.catalog_id}",
                )
            spec.image = catalog_entry["image"]
            spec.environment = {
                **catalog_entry["default_env"],
                **(spec.environment or {}),
            }
            if catalog_entry.get("healthcheck") is not None:
                spec.healthcheck = catalog_entry["healthcheck"]
            if intent.persistence:
                vol_name = f"{service_name}_data"
                _append_volume(
                    spec, f"{vol_name}:{catalog_entry['default_db_volume']}"
                )
                volumes[vol_name] = {}
        else:
            if not intent.image:
                return PrepareResult(
                    ok=False,
                    error=f"Image must be specified for custom service: {service_name}",
                )
            spec.image = intent.image
            if intent.persistence:
                mount_path = (
                    intent.persistence.path if intent.persistence.path else "/data"
                )
                vol_name = f"{service_name}_data"
                _append_volume(spec, f"{vol_name}:{mount_path}")
                volumes[vol_name] = {}

        if intent.volume_mounts:
            for mount in intent.volume_mounts:
                _append_volume(spec, _volume_mount_to_compose_string(mount))

        if intent.resources:
            limits = RESOURCE_LIMITS_MAP.get(intent.resources)
            if limits:
                spec.deploy = DeploySpec(
                    resources=DeployResources(
                        limits=DeployResourcesLimits(
                            cpus=limits["cpus"],
                            memory=limits["memory"],
                        )
                    )
                )

        if intent.exposure == "public":
            container_port = 80
            if intent.kind == "catalog":
                catalog_entry = CATALOG_REGISTRY.get(intent.catalog_id or "")
                if catalog_entry:
                    container_port = catalog_entry["container_port"]
            elif intent.container_port is not None:
                container_port = intent.container_port

            host_port: int | None = None
            if intent.host_port is not None:
                host_port = intent.host_port

            if (
                host_port is None
                and previous_def is not None
                and service_name in previous_def.services
            ):
                prev_ports = previous_def.services[service_name].ports or []
                if prev_ports:
                    prev_host_port = extract_host_port(prev_ports[0])
                    if prev_host_port is not None:
                        host_port = prev_host_port

            if host_port is None:
                while next_auto_port <= 9000:
                    if next_auto_port not in occupied_ports:
                        host_port = next_auto_port
                        occupied_ports.add(next_auto_port)
                        break
                    next_auto_port += 1

            if host_port is None:
                return PrepareResult(
                    ok=False,
                    error=(
                        f"Could not allocate a free host port in the 8000-9000 range "
                        f"for service '{service_name}'"
                    ),
                )

            spec.ports = [f"{host_port}:{container_port}"]

        services[service_name] = spec

    inject_db_healthchecks(services)

    prepared = PreparedStack(
        stack_name=input.stack_name,
        intent=input.intent,
        services=services,
        networks=networks,
        volumes=volumes,
        config_files=input.config_files,
        hash="",
    )
    prepared.hash = calculate_canonical_hash(prepared)
    return PrepareResult(ok=True, prepared=prepared)


__all__ = [
    "CATALOG_REGISTRY",
    "DEFAULT_LOGGING",
    "PrepareResult",
    "PreparedStack",
    "RESOURCE_LIMITS_MAP",
    "calculate_canonical_hash",
    "extract_host_port",
    "get_occupied_ports",
    "prepare_stack_draft",
]
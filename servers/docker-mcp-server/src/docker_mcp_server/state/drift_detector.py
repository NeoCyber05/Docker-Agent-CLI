"""Drift detection: compare desired stack YAML with live Docker containers.

Parity: ``src/state/driftDetector.ts:1-255``.

Uses the Phase-2 ``EngineClient`` Protocol only; Phase 3 supplies the real
implementation.
"""

import asyncio
from pathlib import Path
from typing import Any

from docker_mcp_server.services.docker.types import ContainerInspect, EngineClient
from docker_mcp_server.state.env_file import merge_env, read_env_file
from docker_mcp_server.state.secret_redactor import redact_env
from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.types.stack import (
    FieldChange,
    ServiceDiff,
    ServiceSnapshot,
    ServiceSpec,
    StackDiff,
)

RUNTIME_ALLOWLIST = {
    "PATH",
    "HOME",
    "HOSTNAME",
    "TERM",
    "LANG",
    "LC_ALL",
    "PWD",
    "SHLVL",
    "_",
}


def _parse_actual_ports(
    network_ports: dict[str, list[Any] | None],
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for container_port_proto, bindings in network_ports.items():
        if not bindings:
            continue
        if "/" in container_port_proto:
            container_port, proto = container_port_proto.split("/", 1)
        else:
            container_port, proto = container_port_proto, "tcp"
        for binding in bindings:
            host_port = binding.host_port
            if not host_port:
                continue
            if proto == "tcp":
                mapping = f"{host_port}:{container_port}"
            else:
                mapping = f"{host_port}:{container_port}/{proto}"
            if mapping in seen:
                continue
            seen.add(mapping)
            out.append(mapping)
    return sorted(out)


def _normalize_volume(vol: str, stack_name: str) -> str:
    parts = vol.split(":")
    if len(parts) < 2:
        return vol
    source, target = parts[0], parts[1]
    rest = [p for p in parts[2:] if p not in ("rw", "ro")]
    prefix = f"{stack_name}_"
    if source.startswith(prefix):
        source = source[len(prefix) :]
    if rest:
        return f"{source}:{target}:{':'.join(rest)}"
    return f"{source}:{target}"


def _env_array_to_map(env: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in env:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in RUNTIME_ALLOWLIST:
            continue
        out[key] = value
    return out


def _desired_env(spec: ServiceSpec, cwd: str) -> dict[str, str]:
    from_env_file: dict[str, str] = {}
    for f in spec.env_file or []:
        p = f if Path(f).is_absolute() else str(Path(cwd) / f)
        from_env_file.update(read_env_file(p))
    return merge_env(from_env_file, spec.environment or {})


def _snapshot(
    *,
    image: str,
    command: str | list[str] | None,
    ports: list[str],
    env: dict[str, str],
    volumes: list[str],
    replica_count: int,
    stack_name: str,
    state: str | None = None,
) -> ServiceSnapshot:
    kwargs: dict[str, Any] = {
        "image": image,
        "command": command,
        "ports": ports,
        "env": redact_env(env, stack_name),
        "volumes": volumes,
        "replica_count": replica_count,
    }
    if state is not None:
        kwargs["state"] = state
    return ServiceSnapshot.model_validate(kwargs)


def _field_change(field: str, from_value: Any, to_value: Any) -> FieldChange:
    return FieldChange.model_validate(
        {"field": field, "from_": from_value, "to": to_value}
    )


def _stack_diff(
    stack_name: str, status: str, service_diffs: list[ServiceDiff]
) -> StackDiff:
    return StackDiff.model_validate(
        {
            "stack_name": stack_name,
            "status": status,
            "service_diffs": service_diffs,
        }
    )


def _diff_snapshots(
    desired: ServiceSnapshot,
    actual: ServiceSnapshot,
    declared_env_keys: set[str],
) -> list[FieldChange]:
    changes: list[FieldChange] = []

    for field in ("image", "replica_count"):
        if getattr(desired, field) != getattr(actual, field):
            changes.append(
                _field_change(field, getattr(desired, field), getattr(actual, field))
            )

    if desired.command is not None and desired.command != actual.command:
        changes.append(_field_change("command", desired.command, actual.command))

    desired_ports = sorted(desired.ports)
    actual_ports = sorted(actual.ports)
    if desired_ports != actual_ports:
        changes.append(_field_change("ports", desired_ports, actual_ports))

    desired_volumes = sorted(desired.volumes)
    actual_volumes = sorted(actual.volumes)
    if desired_volumes != actual_volumes:
        changes.append(_field_change("volumes", desired_volumes, actual_volumes))

    for key in declared_env_keys:
        if key in desired.env.secret_keys or key in actual.env.secret_keys:
            continue
        a = desired.env.visible.get(key)
        b = actual.env.visible.get(key)
        if a != b:
            changes.append(_field_change(f"env.{key}", a, b))

    for key in desired.env.secret_keys:
        a = desired.env.secret_hashes_by_key.get(key)
        b = actual.env.secret_hashes_by_key.get(key)
        if a != b:
            changes.append(_field_change(f"env.{key}", "***", "***"))

    return changes


async def detect_drift(
    stack_name: str,
    store: StateStore,
    engine: EngineClient,
    cwd: str,
) -> StackDiff:
    definition = store.read(stack_name)
    if definition is None:
        return _stack_diff(stack_name, "missing", [])

    summaries = await engine.list_containers(
        all=True,
        filters={"label": [f"com.docker.compose.project={stack_name}"]},
    )
    inspects = await asyncio.gather(*[engine.inspect(s.id) for s in summaries])

    by_service: dict[str, list[ContainerInspect]] = {}
    for insp in inspects:
        service = insp.config.labels.get("com.docker.compose.service")
        if not service:
            continue
        by_service.setdefault(service, []).append(insp)

    desired_services = set(definition.services.keys())
    actual_services = set(by_service.keys())

    service_diffs: list[ServiceDiff] = []
    for svc in sorted(desired_services | actual_services):
        spec = definition.services.get(svc)
        containers = by_service.get(svc, [])

        declared_env = _desired_env(spec, cwd) if spec else {}
        declared_env_keys = set(declared_env.keys())

        desired_snap: ServiceSnapshot | None = None
        actual_snap: ServiceSnapshot | None = None

        if spec is not None:
            desired_snap = _snapshot(
                image=spec.image,
                command=spec.command if spec.command is not None else None,
                ports=sorted(spec.ports or []),
                env=declared_env,
                volumes=sorted(spec.volumes or []),
                replica_count=spec.scale if spec.scale is not None else 1,
                stack_name=stack_name,
            )

        if containers:
            first = containers[0]
            actual_env = _env_array_to_map(first.config.env or [])
            actual_snap = _snapshot(
                image=first.config.image,
                command=first.config.cmd,
                ports=_parse_actual_ports(first.network_settings.ports or {}),
                env=actual_env,
                volumes=[
                    _normalize_volume(v, stack_name)
                    for v in (first.host_config.binds or [])
                ],
                replica_count=len(containers),
                stack_name=stack_name,
                state=first.state.status,
            )

        if desired_snap is not None and actual_snap is not None:
            changes = _diff_snapshots(desired_snap, actual_snap, declared_env_keys)
        elif desired_snap is not None:
            changes = [_field_change("service", "desired", "missing")]
        else:
            changes = [_field_change("service", "missing", "extra")]

        service_diffs.append(
            ServiceDiff(
                service=svc,
                desired=desired_snap,
                actual=actual_snap,
                changes=changes,
            )
        )

    all_in_sync = all(len(sd.changes) == 0 for sd in service_diffs)
    all_desired_missing = all(
        sd.desired is not None and sd.actual is None for sd in service_diffs
    )
    any_extra = any(sd.desired is None and sd.actual is not None for sd in service_diffs)

    if all_in_sync:
        status: Any = "in_sync"
    elif all_desired_missing:
        status = "missing"
    elif any_extra:
        status = "extra"
    else:
        status = "drift"

    return _stack_diff(stack_name, status, service_diffs)


__all__ = ["detect_drift"]


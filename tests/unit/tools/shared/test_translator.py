"""Parity tests for translator — mirrors src/tools/shared/translator.ts behavior."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from docker_agent.state.state_store import StateStore
from docker_agent.tool import ToolContext
from docker_agent.tools.shared.spec_schemas import StackDraft
from docker_agent.tools.shared.translator import (
    calculate_canonical_hash,
    extract_host_port,
    get_occupied_ports,
    prepare_stack_draft,
)
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


class FakeDockerEngine:
    async def list_containers(self, **kwargs: Any) -> list[Any]:
        return []

    async def inspect(self, container_id: str) -> Any:
        raise AssertionError("not expected")


def _make_ctx(tmp_path: Any, store: StateStore) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        state_store=store,
        docker_engine=FakeDockerEngine(),
        compose_runner=object(),  # type: ignore[arg-type]
        abort_signal=asyncio.Event(),
    )


@pytest.mark.asyncio
async def test_prepare_stack_draft_catalog_mapping(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "cache",
            "services": [{"name": "cache", "kind": "catalog", "catalogId": "redis:7"}],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.services["cache"].image == "redis:7-alpine"
    assert result.prepared.services["cache"].environment == {}


@pytest.mark.asyncio
async def test_prepare_stack_draft_custom_image_and_persistence(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "app",
            "services": [
                {
                    "name": "app",
                    "kind": "custom",
                    "image": "node:20-alpine",
                    "persistence": {"path": "/app/data"},
                }
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.services["app"].image == "node:20-alpine"
    assert result.prepared.volumes == {"app_data": {}}
    assert result.prepared.services["app"].volumes == ["app_data:/app/data"]


@pytest.mark.asyncio
async def test_prepare_stack_draft_public_port_auto_allocation(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "web",
            "services": [
                {
                    "name": "web",
                    "kind": "catalog",
                    "catalogId": "nginx:1.27",
                    "exposure": "public",
                }
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.services["web"].ports == ["8000:80"]


@pytest.mark.asyncio
async def test_prepare_stack_draft_reuses_previous_host_port(tmp_path: Any) -> None:
    root = tmp_path / ".docker-agent"
    store = StateStore(str(root))
    store.write(
        "demo",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="demo",
                created_at="2026-01-01T00:00:00.000Z",
                last_applied=None,
                intent="old",
                provider="test",
                generated_by="test",
                env_file_sources={},
            ),
            services={
                "web": ServiceSpec(image="nginx:1.27-alpine", ports=["8123:80"]),
            },
        ),
    )
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "web",
            "services": [
                {
                    "name": "web",
                    "kind": "catalog",
                    "catalogId": "nginx:1.27",
                    "exposure": "public",
                }
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.services["web"].ports == ["8123:80"]


@pytest.mark.asyncio
async def test_prepare_stack_draft_resource_limits(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "web",
            "services": [
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:1.27-alpine",
                    "resources": "medium",
                }
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    deploy = result.prepared.services["web"].deploy
    assert deploy is not None
    assert deploy.resources is not None
    assert deploy.resources.limits is not None
    assert deploy.resources.limits.cpus == "1.0"
    assert deploy.resources.limits.memory == "1Gi"


def test_extract_host_port() -> None:
    assert extract_host_port("8080:80") == 8080
    assert extract_host_port("8080:80/tcp") == 8080
    assert extract_host_port("80") is None


def test_calculate_canonical_hash_is_stable() -> None:
    from docker_agent.tools.shared.translator import PreparedStack

    prepared = PreparedStack(
        stack_name="demo",
        intent="x",
        services={
            "b": ServiceSpec(image="nginx"),
            "a": ServiceSpec(image="redis"),
        },
        networks={"default": {}},
        volumes={},
        hash="",
    )
    h1 = calculate_canonical_hash(prepared)
    h2 = calculate_canonical_hash(prepared)
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.asyncio
async def test_get_occupied_ports_skips_failed_inspect(tmp_path: Any) -> None:
    from mocks.mock_docker_engine import MockDockerEngine

    class PartiallyBrokenEngine(MockDockerEngine):
        async def inspect(self, container_id: str):
            if container_id == "broken":
                raise RuntimeError("inspect failed")
            return await super().inspect(container_id)

    engine = PartiallyBrokenEngine()
    engine.containers.append(
        {
            "Id": "broken",
            "Names": ["/broken"],
            "State": "running",
            "Labels": {},
        }
    )
    engine.containers.append(
        {
            "Id": "healthy",
            "Names": ["/healthy"],
            "State": "running",
            "Labels": {},
        }
    )
    engine.inspect_by_id["healthy"] = {
        "Id": "healthy",
        "Name": "/healthy",
        "State": {"Status": "running"},
        "Config": {"Image": "nginx", "Env": [], "Labels": {}},
        "HostConfig": {"Binds": None, "PortBindings": {}},
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9090"}]}
        },
        "RestartCount": 0,
    }

    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = ToolContext(
        cwd=str(tmp_path),
        state_store=store,
        docker_engine=engine,
        compose_runner=object(),  # type: ignore[arg-type]
        abort_signal=asyncio.Event(),
    )

    occupied = await get_occupied_ports(ctx, "demo")
    assert occupied == {9090}


@pytest.mark.asyncio
async def test_prepare_stack_draft_multi_network(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "tiered",
            "networks": [
                {"name": "frontend"},
                {"name": "backend", "internal": True},
            ],
            "services": [
                {
                    "name": "web",
                    "kind": "catalog",
                    "catalogId": "nginx:1.27",
                    "exposure": "public",
                    "networks": ["frontend"],
                },
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "node:20-alpine",
                    "networks": ["frontend", "backend"],
                },
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.networks == {
        "default": {},
        "frontend": {},
        "backend": {"internal": True},
    }
    assert result.prepared.services["web"].networks == ["frontend"]
    assert result.prepared.services["api"].networks == ["frontend", "backend"]


@pytest.mark.asyncio
async def test_prepare_stack_draft_named_volumes_and_mounts(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "storage",
            "volumes": [
                {
                    "name": "pgdata",
                    "driver": "local",
                    "driverOpts": {"type": "none", "device": "tmpfs"},
                }
            ],
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "postgresql:16",
                    "volumeMounts": [
                        {"volume": "pgdata", "target": "/var/lib/postgresql/data", "readOnly": True}
                    ],
                }
            ],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.volumes == {
        "pgdata": {"driver": "local", "driver_opts": {"type": "none", "device": "tmpfs"}},
    }
    assert result.prepared.services["db"].volumes == [
        "pgdata:/var/lib/postgresql/data:ro"
    ]


@pytest.mark.asyncio
async def test_prepare_stack_draft_backward_compat_default_network(tmp_path: Any) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = _make_ctx(tmp_path, store)
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "cache",
            "services": [{"name": "cache", "kind": "catalog", "catalogId": "redis:7"}],
        }
    )
    result = await prepare_stack_draft(draft, ctx)
    assert result.ok is True
    assert result.prepared is not None
    assert result.prepared.networks == {"default": {}}
    assert result.prepared.services["cache"].networks == ["default"]
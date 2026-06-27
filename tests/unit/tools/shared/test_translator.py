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
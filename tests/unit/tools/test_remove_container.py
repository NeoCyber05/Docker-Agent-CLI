"""Tests for remove_container tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from docker_agent.state.state_store import StateStore
from docker_agent.tools.remove_container import (
    MAX_CONTAINERS_PER_CALL,
    RemoveContainerInput,
    remove_container,
)
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_docker_engine import MockDockerEngine
from tests.unit.tools.conftest import drain, drain_with_progress, make_ctx


def _seed_stack(store: StateStore, name: str) -> None:
    store.write(
        name,
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name=name,
                created_at="x",
                last_applied="x",
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={},
            ),
            services={"web": ServiceSpec(image="nginx:1.27")},
        ),
    )


def _inspect_payload(project: str | None) -> dict:
    labels = {"com.docker.compose.project": project} if project else {}
    return {
        "Id": "abc",
        "Name": "/container-1",
        "State": {"Status": "exited"},
        "Config": {"Image": "nginx", "Labels": labels},
        "HostConfig": {},
        "NetworkSettings": {"Ports": {}},
    }


@pytest.mark.asyncio
async def test_remove_container_force_rm_success(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)

    async def fake_run(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        assert args == ["rm", "-f", "web-1"]
        assert cwd == str(tmp_project)
        return 0, "", ""

    with patch(
        "docker_agent.tools.remove_container._run_docker",
        new=AsyncMock(side_effect=fake_run),
    ):
        progress, result = await drain_with_progress(
            remove_container.call(
                RemoveContainerInput(containers=["web-1"], force=True),
                ctx,
            )
        )

    assert result.ok is True
    assert result.removed == ["web-1"]
    assert result.failed == []
    assert any("Force removing web-1" in p.msg for p in progress)


@pytest.mark.asyncio
async def test_remove_container_stop_then_rm_without_force(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)
    calls: list[list[str]] = []

    async def fake_run(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "", ""

    with patch(
        "docker_agent.tools.remove_container._run_docker",
        new=AsyncMock(side_effect=fake_run),
    ):
        result = await drain(
            remove_container.call(
                RemoveContainerInput(containers=["db-1"], force=False),
                ctx,
            )
        )

    assert result.ok is True
    assert calls == [["stop", "db-1"], ["rm", "db-1"]]


@pytest.mark.asyncio
async def test_remove_container_stop_only(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)

    async def fake_run(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        assert args == ["stop", "cache-1"]
        return 0, "", ""

    with patch(
        "docker_agent.tools.remove_container._run_docker",
        new=AsyncMock(side_effect=fake_run),
    ):
        result = await drain(
            remove_container.call(
                RemoveContainerInput(containers=["cache-1"], stop_only=True),
                ctx,
            )
        )

    assert result.ok is True
    assert result.removed == ["cache-1"]


@pytest.mark.asyncio
async def test_remove_container_not_found(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)

    async def fake_run(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        return 1, "", "No such container: missing"

    with patch(
        "docker_agent.tools.remove_container._run_docker",
        new=AsyncMock(side_effect=fake_run),
    ):
        result = await drain(
            remove_container.call(
                RemoveContainerInput(containers=["missing"]),
                ctx,
            )
        )

    assert result.ok is False
    assert result.removed == []
    assert len(result.failed) == 1
    assert result.failed[0].name == "missing"
    assert result.failed[0].exit_code == 1


def test_remove_container_needs_permission() -> None:
    assert remove_container.needs_permission(RemoveContainerInput(containers=["x"])) is True


def test_remove_container_rejects_wildcard_names() -> None:
    with pytest.raises(ValidationError):
        RemoveContainerInput(containers=["*"])


def test_remove_container_rejects_too_many_containers() -> None:
    with pytest.raises(ValidationError):
        RemoveContainerInput(
            containers=[f"c{i}" for i in range(MAX_CONTAINERS_PER_CALL + 1)]
        )


@pytest.mark.asyncio
async def test_remove_container_blocks_managed_stack_containers(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    _seed_stack(store, "webapp")
    engine = MockDockerEngine()
    engine.inspect_by_id["webapp-nginx-1"] = _inspect_payload("webapp")
    ctx = make_ctx(tmp_project, docker_engine=engine)
    ctx.state_store = store

    result = await drain(
        remove_container.call(
            RemoveContainerInput(containers=["webapp-nginx-1"]),
            ctx,
        )
    )

    assert result.ok is False
    assert result.removed == []
    assert len(result.blocked) == 1
    assert "destroy_stack" in result.blocked[0].reason


@pytest.mark.asyncio
async def test_remove_container_allows_untracked_compose_project(tmp_project: Path) -> None:
    engine = MockDockerEngine()
    engine.inspect_by_id["web-app-nginx-1"] = _inspect_payload("web-app")
    ctx = make_ctx(tmp_project, docker_engine=engine)

    async def fake_run(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        return 0, "", ""

    with patch(
        "docker_agent.tools.remove_container._run_docker",
        new=AsyncMock(side_effect=fake_run),
    ):
        result = await drain(
            remove_container.call(
                RemoveContainerInput(containers=["web-app-nginx-1"]),
                ctx,
            )
        )

    assert result.ok is True
    assert result.removed == ["web-app-nginx-1"]
    assert result.blocked == []

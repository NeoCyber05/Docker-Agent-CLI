"""Tests for stop_stack tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from tool_helpers import drain, make_ctx

from docker_mcp_server.config import stack_state_yaml_path
from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.tools.stop_stack import StopStackInput, stop_stack
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def _seed_stack(store: StateStore, name: str) -> None:
    store.write(
        name,
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
                name=name,
                created_at="x",
                last_applied="x",
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={},
            ),
            services={
                "wordpress": ServiceSpec(image="wordpress:latest"),
                "mysql": ServiceSpec(image="mysql:8.0"),
            },
        ),
    )


def _write_stack_yaml(tmp_project: Path, stack_name: str) -> None:
    yaml_path = Path(stack_state_yaml_path(stack_name, str(tmp_project)))
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "services:\n  wordpress:\n    image: wordpress:latest\n  mysql:\n    image: mysql:8.0\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_stop_stack_calls_compose_stop_for_all_services(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "wp-new")
    _write_stack_yaml(tmp_project, "wp-new")
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.state_store = store

    result = await drain(stop_stack.call(StopStackInput(stack_name="wp-new"), ctx))

    assert result.ok is True
    bound = runner.bound_for("wp-new")
    assert bound.stop_calls == [{"services": None}]


@pytest.mark.asyncio
async def test_stop_stack_can_target_specific_services(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "wp-new")
    _write_stack_yaml(tmp_project, "wp-new")
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.state_store = store

    result = await drain(
        stop_stack.call(
            StopStackInput(stack_name="wp-new", services=["wordpress"]),
            ctx,
        )
    )

    assert result.ok is True
    assert result.stopped_services == ["wordpress"]
    bound = runner.bound_for("wp-new")
    assert bound.stop_calls == [{"services": ["wordpress"]}]


@pytest.mark.asyncio
async def test_stop_stack_missing_yaml_returns_not_ok(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)

    result = await drain(stop_stack.call(StopStackInput(stack_name="missing"), ctx))

    assert result.ok is False
    assert result.exit_code == 1
    assert result.reason == "stack_file_not_found"


@pytest.mark.asyncio
async def test_stop_stack_needs_permission() -> None:
    assert stop_stack.needs_permission(StopStackInput(stack_name="demo")) is True




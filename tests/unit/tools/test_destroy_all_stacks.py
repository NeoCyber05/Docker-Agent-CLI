"""Parity tests for destroy_all_stacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.state.state_store import StateStore
from src.tools.destroy_all_stacks import DestroyAllStacksInput, destroy_all_stacks
from src.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine
from tests.unit.tools.conftest import drain, make_ctx


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


@pytest.mark.asyncio
async def test_destroy_all_stacks_invokes_down_for_each_stack(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "a")
    _seed_stack(store, "b")
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.state_store = store

    result = await drain(destroy_all_stacks.call(DestroyAllStacksInput(), ctx))

    assert sorted(result.destroyed) == ["a", "b"]
    assert sorted(call["stack_name"] for call in runner.for_stack_calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_destroy_all_stacks_records_failures_and_continues(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "a")
    _seed_stack(store, "b")
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.state_store = store

    original_for_stack = runner.for_stack

    def failing_for_stack(stack_name: str, yaml_path: str):
        if stack_name == "a":
            raise RuntimeError("boom")
        return original_for_stack(stack_name, yaml_path)

    runner.for_stack = failing_for_stack  # type: ignore[method-assign]

    result = await drain(destroy_all_stacks.call(DestroyAllStacksInput(), ctx))

    assert result.destroyed == ["b"]
    assert len(result.failed) == 1
    assert result.failed[0].stack == "a"
    assert result.failed[0].exit_code == -1
    assert [call["stack_name"] for call in runner.for_stack_calls] == ["b"]
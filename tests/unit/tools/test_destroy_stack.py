"""Parity tests for destroy_stack."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.state.state_store import StateStore
from src.tools.destroy_stack import DestroyStackInput, destroy_stack
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
async def test_destroy_stack_calls_for_stack_down(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "webapp")
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.state_store = store

    result = await drain(
        destroy_stack.call(
            DestroyStackInput(stack_name="webapp", remove_volumes=True),
            ctx,
        )
    )

    assert result.ok is True
    assert runner.for_stack_calls[0]["stack_name"] == "webapp"
    bound = runner.bound_for("webapp")
    assert bound.down_calls == [{"volumes": True}]



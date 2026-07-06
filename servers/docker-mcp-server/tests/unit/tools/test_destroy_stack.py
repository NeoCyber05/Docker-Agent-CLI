"""Parity tests for destroy_stack."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from tool_helpers import drain, make_ctx

from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.tools.destroy_stack import DestroyStackInput, destroy_stack
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


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


@pytest.mark.asyncio
async def test_destroy_stack_missing_yaml_returns_not_ok(tmp_project: Path) -> None:
    ctx = make_ctx(tmp_project)

    result = await drain(
        destroy_stack.call(DestroyStackInput(stack_name="orphan"), ctx)
    )

    assert result.ok is False
    assert result.exit_code == 1
    assert result.reason == "stack_file_not_found"
    assert "remove_container" in (result.message or "")


@pytest.mark.asyncio
async def test_destroy_stack_history_uses_session_id(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    runner = MockComposeRunner(str(tmp_project))
    _seed_stack(store, "webapp")
    ctx = replace(
        make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner),
        session_id="sess-destroy",
    )
    ctx.state_store = store

    with patch.object(store, "append_history", wraps=store.append_history) as append_history:
        result = await drain(
            destroy_stack.call(DestroyStackInput(stack_name="webapp"), ctx)
        )

    assert result.ok is True
    destroy_events = [
        call.args[0]
        for call in append_history.call_args_list
        if call.args[0].action == "destroy"
    ]
    assert destroy_events
    assert destroy_events[0].session_id == "sess-destroy"





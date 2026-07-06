"""Parity tests for list_stacks â€” mirrors listStacks.test.ts."""

from __future__ import annotations

import pytest
from mocks.mock_compose_runner import MockComposeRunner
from mocks.mock_docker_engine import MockDockerEngine
from tool_helpers import drain_with_progress, make_ctx

from docker_mcp_server.tools.list_stacks import list_stacks
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


@pytest.mark.asyncio
async def test_returns_summary_list(tmp_project) -> None:
    ctx = make_ctx(
        tmp_project,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
    )
    ctx.state_store.write(
        "a",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="a",
                created_at="x",
                last_applied=None,
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={},
            ),
            services={"web": ServiceSpec(image="nginx")},
        ),
    )

    _, result = await drain_with_progress(
        list_stacks.call(list_stacks.input_schema.model_validate({}), ctx)
    )
    assert [stack.name for stack in result.stacks] == ["a"]



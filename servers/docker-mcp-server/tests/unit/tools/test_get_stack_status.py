"""Parity tests for get_stack_status â€” mirrors getStackStatus.test.ts."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from tool_helpers import drain_with_progress, make_ctx

from docker_mcp_server.config import stack_states_dir
from docker_mcp_server.tools.get_stack_status import get_stack_status
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner


async def _canned_logs() -> AsyncIterator[str]:
    yield "boot PASSWORD=hunter2 ready\n"


@pytest.mark.asyncio
async def test_scrubs_secret_values_appearing_in_log_tail(tmp_project) -> None:
    stacks_dir = stack_states_dir(tmp_project)
    stacks_dir_path = __import__("pathlib").Path(stacks_dir)
    stacks_dir_path.mkdir(parents=True, exist_ok=True)
    (stacks_dir_path / "web.yaml").write_text("services: {}\n", encoding="utf-8")

    runner = MockComposeRunner(str(tmp_project))

    def on_created(bound) -> None:
        bound._logs_impl = lambda **_kwargs: _canned_logs()

    runner.on_bound_runner_created = on_created
    ctx = make_ctx(tmp_project, compose_runner=runner)
    ctx.state_store.write(
        "web",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="web",
                created_at="x",
                last_applied=None,
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={},
            ),
            services={
                "web": ServiceSpec(
                    image="nginx",
                    environment={"PASSWORD": "hunter2"},
                )
            },
        ),
    )

    _, result = await drain_with_progress(
        get_stack_status.call(
            get_stack_status.input_schema.model_validate({"stackName": "web"}),
            ctx,
        )
    )
    assert "PASSWORD=***" in result.log_tail
    assert "hunter2" not in result.log_tail



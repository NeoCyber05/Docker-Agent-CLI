"""Parity tests for get_logs â€” mirrors getLogs.test.ts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tool_helpers import drain_with_progress, make_ctx

from docker_mcp_server.config import stack_states_dir
from docker_mcp_server.tools.get_logs import get_logs
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner

_MAX_BYTES = 16 * 1024


def _write_stack_yaml(tmp_project: Path, name: str) -> None:
    stacks_dir = Path(stack_states_dir(tmp_project))
    stacks_dir.mkdir(parents=True, exist_ok=True)
    (stacks_dir / f"{name}.yaml").write_text("services: {}\n", encoding="utf-8")


def _ctx_with_runner(tmp_project: Path, runner: MockComposeRunner):
    ctx = make_ctx(tmp_project, compose_runner=runner)
    return ctx


@pytest.mark.asyncio
async def test_returns_explanatory_result_when_stack_yaml_missing(tmp_project) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = _ctx_with_runner(tmp_project, runner)
    _, result = await drain_with_progress(
        get_logs.call(
            get_logs.input_schema.model_validate({"stackName": "ghost"}),
            ctx,
        )
    )
    assert "ghost" in result.log_tail
    assert "not found" in result.log_tail.lower()
    assert result.line_count == 0


@pytest.mark.asyncio
async def test_drains_canned_log_lines_and_counts_them(tmp_project) -> None:
    _write_stack_yaml(tmp_project, "web")
    runner = MockComposeRunner(str(tmp_project))

    async def logs_impl(**_kwargs: object) -> AsyncIterator[str]:
        yield "line one\n"
        yield "line two\n"

    runner.on_bound_runner_created = lambda b: setattr(b, "_logs_impl", logs_impl)
    ctx = _ctx_with_runner(tmp_project, runner)
    _, result = await drain_with_progress(
        get_logs.call(
            get_logs.input_schema.model_validate({"stackName": "web"}),
            ctx,
        )
    )
    assert "line one" in result.log_tail
    assert "line two" in result.log_tail
    assert result.line_count == 2
    assert result.truncated is False


@pytest.mark.asyncio
async def test_passes_service_and_tail_lines_through(tmp_project) -> None:
    _write_stack_yaml(tmp_project, "web")
    runner = MockComposeRunner(str(tmp_project))
    ctx = _ctx_with_runner(tmp_project, runner)
    await drain_with_progress(
        get_logs.call(
            get_logs.input_schema.model_validate(
                {"stackName": "web", "service": "api", "tailLines": 25}
            ),
            ctx,
        )
    )
    bound = runner.bound_for("web")
    assert bound.logs_calls[0]["service"] == "api"
    assert bound.logs_calls[0]["tail_lines"] == 25
    assert not bound.logs_calls[0]["follow"]


@pytest.mark.asyncio
async def test_redacts_secret_values_using_collect_secret_keys(tmp_project) -> None:
    _write_stack_yaml(tmp_project, "web")
    ctx = _ctx_with_runner(tmp_project, MockComposeRunner(str(tmp_project)))
    ctx.state_store.write(
        "web",
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
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

    async def logs_impl(**_kwargs: object) -> AsyncIterator[str]:
        yield "starting with PASSWORD=hunter2 in env\n"

    runner = MockComposeRunner(str(tmp_project))
    runner.on_bound_runner_created = lambda b: setattr(b, "_logs_impl", logs_impl)
    ctx = _ctx_with_runner(tmp_project, runner)
    ctx.state_store.write(
        "web",
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
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
        get_logs.call(
            get_logs.input_schema.model_validate({"stackName": "web"}),
            ctx,
        )
    )
    assert "PASSWORD=***" in result.log_tail
    assert "hunter2" not in result.log_tail


@pytest.mark.asyncio
async def test_caps_output_to_16kb_keeping_newest_lines(tmp_project) -> None:
    _write_stack_yaml(tmp_project, "web")
    runner = MockComposeRunner(str(tmp_project))

    async def logs_impl(**_kwargs: object) -> AsyncIterator[str]:
        for i in range(4000):
            yield f"log line number {i}\n"

    runner.on_bound_runner_created = lambda b: setattr(b, "_logs_impl", logs_impl)
    ctx = _ctx_with_runner(tmp_project, runner)
    _, result = await drain_with_progress(
        get_logs.call(
            get_logs.input_schema.model_validate({"stackName": "web"}),
            ctx,
        )
    )
    assert result.truncated is True
    assert len(result.log_tail.encode("utf-8")) <= _MAX_BYTES
    assert "log line number 3999" in result.log_tail
    assert "log line number 0\n" not in result.log_tail
    kept_lines = [line for line in result.log_tail.split("\n") if line]
    first_kept = int(kept_lines[0].replace("log line number ", ""))
    last_kept = int(kept_lines[-1].replace("log line number ", ""))
    assert first_kept < last_kept
    assert last_kept == 3999



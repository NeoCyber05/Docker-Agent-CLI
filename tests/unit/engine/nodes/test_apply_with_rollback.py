"""Tests for apply_with_rollback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from docker_agent.engine.nodes.apply_with_rollback import (
    ApplyWithRollbackParams,
    run_apply_with_rollback,
)
from docker_agent.tools.apply_stack import ApplyStackResult
from docker_agent.types.events import ToolCall, ToolResult


@pytest.mark.asyncio
async def test_apply_with_rollback_success(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    ok_result = ApplyStackResult(ok=True, exit_code=0, yaml_path="/tmp/x.yaml")

    with patch(
        "docker_agent.engine.nodes.apply_with_rollback._run_apply_tool",
        new=AsyncMock(return_value=ok_result),
    ):
        result = await run_apply_with_rollback(
            ApplyWithRollbackParams(
                stack_name="web",
                desired_yaml="services:",
                config_files=[],
                ctx=ctx,
                emit=events.append,
            )
        )

    assert result.ok is True
    assert result.result_message == "Stack applied."


@pytest.mark.asyncio
async def test_apply_with_rollback_success_with_warnings(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    ok_result = ApplyStackResult(
        ok=True,
        exit_code=0,
        yaml_path="/tmp/x.yaml",
        warnings=["db: FATAL: password authentication failed"],
    )

    with patch(
        "docker_agent.engine.nodes.apply_with_rollback._run_apply_tool",
        new=AsyncMock(return_value=ok_result),
    ):
        result = await run_apply_with_rollback(
            ApplyWithRollbackParams(
                stack_name="web",
                desired_yaml="services:",
                config_files=[],
                ctx=ctx,
                emit=events.append,
            )
        )

    assert result.ok is True
    assert "Stack applied." in result.result_message
    assert "password authentication failed" in result.result_message


@pytest.mark.asyncio
async def test_apply_with_rollback_failure_triggers_rollback(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    fail_result = ApplyStackResult(
        ok=False,
        exit_code=1,
        yaml_path="/tmp/x.yaml",
        error_output="Bind for 0.0.0.0:8080 failed: port is already allocated",
        healthy=False,
        unhealthy_services=["web"],
    )
    restore_ok = ApplyStackResult(ok=True, exit_code=0, yaml_path="/tmp/x.yaml")
    outputs = [fail_result, restore_ok]

    async def fake_run_apply_tool(tool, input_data, _ctx, emit):
        emit(ToolCall(name=tool.name, input=input_data))
        result = outputs.pop(0)
        emit(ToolResult(name=tool.name, output=result))
        return result

    with (
        patch(
            "docker_agent.engine.nodes.apply_with_rollback._run_apply_tool",
            new=fake_run_apply_tool,
        ),
        patch(
            "docker_agent.engine.nodes.apply_with_rollback.capture_known_good",
        ) as mock_known,
        patch(
            "docker_agent.engine.nodes.apply_with_rollback.plan_rollback",
        ) as mock_plan,
    ):
        from docker_agent.state.rollback import KnownGood, RollbackPlan

        mock_known.return_value = KnownGood(
            previous=None, existed_expected=True, recoverable=True, previous_yaml="s:"
        )
        mock_plan.return_value = RollbackPlan(
            strategy="restore_previous", stack_name="web", compose_yaml="s:"
        )

        result = await run_apply_with_rollback(
            ApplyWithRollbackParams(
                stack_name="web",
                desired_yaml="services:",
                config_files=[],
                ctx=ctx,
                emit=events.append,
            )
        )

    types = [getattr(e, "type", None) for e in events]
    assert "rollback_started" in types
    assert "rollback_result" in types
    started_index = types.index("rollback_started")
    rollback_tool_index = next(
        index
        for index, event in enumerate(events)
        if getattr(event, "type", None) == "tool_call"
        and getattr(event, "name", None) == "apply_stack"
        and index > started_index
    )
    started = events[started_index]
    assert "Deploy failed:" in started.detail
    assert "Starting rollback..." in started.detail
    assert "port is already allocated" in started.detail
    assert started_index < rollback_tool_index < types.index("rollback_result")
    assert result.ok is False
    assert "port is already allocated" in result.result_message
    assert "rollback succeeded" in result.result_message


@pytest.mark.asyncio
async def test_legacy_query_apply_with_rollback_reports_reason_before_restore(make_loop_ctx) -> None:
    from unittest.mock import patch

    from docker_agent.query import apply_with_rollback
    from docker_agent.tools.apply_stack import ApplyStackResult

    ctx = make_loop_ctx()
    fail_result = ApplyStackResult(
        ok=False,
        exitCode=1,
        yamlPath="/tmp/x.yaml",
        errorOutput="Bind for 0.0.0.0:8080 failed: port is already allocated",
    )
    restore_ok = ApplyStackResult(ok=True, exitCode=0, yamlPath="/tmp/x.yaml")
    outputs = [fail_result, restore_ok]

    async def fake_run_tool(tool, _input_data, _ctx):
        yield ToolResult(name=tool.name, output=outputs.pop(0))

    with (
        patch("docker_agent.query.run_tool", fake_run_tool),
        patch("docker_agent.query.capture_known_good") as mock_known,
        patch("docker_agent.query.plan_rollback") as mock_plan,
    ):
        from docker_agent.state.rollback import KnownGood, RollbackPlan

        mock_known.return_value = KnownGood(
            previous=None, existed_expected=True, recoverable=True, previous_yaml="s:"
        )
        mock_plan.return_value = RollbackPlan(
            strategy="restore_previous", stack_name="web", compose_yaml="s:"
        )

        events, result = await apply_with_rollback(
            "web", "services:", None, [], ctx
        )

    types = [getattr(event, "type", None) for event in events]
    started_index = types.index("rollback_started")
    rollback_tool_index = next(
        index
        for index, event in enumerate(events)
        if getattr(event, "type", None) == "tool_result"
        and getattr(event, "name", None) == "apply_stack"
        and index > started_index
    )
    started = events[started_index]
    assert "Deploy failed:" in started.detail
    assert "Starting rollback..." in started.detail
    assert "port is already allocated" in started.detail
    assert started_index < rollback_tool_index < types.index("rollback_result")
    assert result["ok"] is False
    assert "port is already allocated" in result["result_message"]

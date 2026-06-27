"""Tests for apply_with_rollback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.engine.nodes.apply_with_rollback import (
    ApplyWithRollbackParams,
    run_apply_with_rollback,
)
from src.tools.apply_stack import ApplyStackResult


@pytest.mark.asyncio
async def test_apply_with_rollback_success(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    ok_result = ApplyStackResult(ok=True, exit_code=0, yaml_path="/tmp/x.yaml")

    with patch(
        "src.engine.nodes.apply_with_rollback._run_apply_tool",
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
async def test_apply_with_rollback_failure_triggers_rollback(make_loop_ctx) -> None:
    ctx = make_loop_ctx()
    events: list[object] = []
    fail_result = ApplyStackResult(
        ok=False,
        exit_code=1,
        yaml_path="/tmp/x.yaml",
        error_output="boom",
        healthy=False,
        unhealthy_services=["web"],
    )
    restore_ok = ApplyStackResult(ok=True, exit_code=0, yaml_path="/tmp/x.yaml")

    with (
        patch(
            "src.engine.nodes.apply_with_rollback._run_apply_tool",
            new=AsyncMock(side_effect=[fail_result, restore_ok]),
        ),
        patch(
            "src.engine.nodes.apply_with_rollback.capture_known_good",
        ) as mock_known,
        patch(
            "src.engine.nodes.apply_with_rollback.plan_rollback",
        ) as mock_plan,
    ):
        from src.state.rollback import KnownGood, RollbackPlan

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
    assert result.ok is False
    assert "rollback succeeded" in result.result_message
"""Tests for inspect_drift tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mocks.mock_compose_runner import MockComposeRunner
from mocks.mock_docker_engine import MockDockerEngine

from docker_agent.tools.inspect_drift import inspect_drift
from docker_agent.types.stack import StackDiff
from tests.unit.tools.conftest import drain_with_progress, make_ctx


@pytest.mark.asyncio
async def test_returns_missing_status_when_stack_not_defined(tmp_project) -> None:
    ctx = make_ctx(
        tmp_project,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
    )
    _, result = await drain_with_progress(
        inspect_drift.call(
            inspect_drift.input_schema.model_validate({"stackName": "ghost"}),
            ctx,
        )
    )
    assert result.status == "missing"
    assert result.service_diffs == []


@pytest.mark.asyncio
async def test_in_sync_does_not_append_drift_detected_history(tmp_project) -> None:
    ctx = make_ctx(
        tmp_project,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
    )
    in_sync = StackDiff(stack_name="web", status="in_sync", service_diffs=[])
    with (
        patch(
            "docker_agent.tools.inspect_drift.detect_drift",
            return_value=in_sync,
        ),
        patch.object(ctx.state_store, "append_history") as append_history,
    ):
        _, result = await drain_with_progress(
            inspect_drift.call(
                inspect_drift.input_schema.model_validate({"stackName": "web"}),
                ctx,
            )
        )

    assert result.status == "in_sync"
    append_history.assert_not_called()


@pytest.mark.asyncio
async def test_drift_appends_drift_detected_history(tmp_project) -> None:
    from dataclasses import replace

    ctx = make_ctx(
        tmp_project,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
    )
    ctx = replace(ctx, session_id="sess-drift")
    drift = StackDiff(stack_name="web", status="drift", service_diffs=[])
    with (
        patch(
            "docker_agent.tools.inspect_drift.detect_drift",
            return_value=drift,
        ),
        patch.object(
            ctx.state_store,
            "append_history",
            wraps=ctx.state_store.append_history,
        ) as append_history,
    ):
        _, result = await drain_with_progress(
            inspect_drift.call(
                inspect_drift.input_schema.model_validate({"stackName": "web"}),
                ctx,
            )
        )

    assert result.status == "drift"
    drift_events = [
        call.args[0]
        for call in append_history.call_args_list
        if call.args[0].action == "drift_detected"
    ]
    assert drift_events
    assert drift_events[0].session_id == "sess-drift"
    assert drift_events[0].details == {"status": "drift"}

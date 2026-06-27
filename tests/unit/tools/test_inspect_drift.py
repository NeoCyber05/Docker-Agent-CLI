"""Tests for inspect_drift tool."""

from __future__ import annotations

import pytest
from mocks.mock_compose_runner import MockComposeRunner
from mocks.mock_docker_engine import MockDockerEngine

from src.tools.inspect_drift import inspect_drift
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
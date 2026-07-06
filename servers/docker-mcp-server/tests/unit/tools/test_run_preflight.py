"""Unit tests for run_preflight shared gate."""

from __future__ import annotations

import pytest
from tool_helpers import make_ctx

from docker_mcp_server.tools.shared.translator import PreparedStack
from docker_mcp_server.tools.validate_spec import run_preflight
from docker_mcp_server.types.stack import ServiceSpec


def _prepared(services: dict[str, ServiceSpec]) -> PreparedStack:
    return PreparedStack(
        stack_name="demo",
        intent="test",
        services=services,
        networks={"default": {}},
        volumes={},
        hash="hash",
    )


@pytest.mark.asyncio
async def test_run_preflight_passes_simple_nginx(tmp_project) -> None:
    prepared = _prepared({"web": ServiceSpec(image="nginx:1.27-alpine")})
    report = await run_preflight(
        stack_name="demo",
        prepared=prepared,
        config_files=None,
        ctx=make_ctx(tmp_project),
    )
    assert report.ok is True
    assert report.failure_reason is None
    assert "image" in report.checks_run


@pytest.mark.asyncio
async def test_run_preflight_blocks_invalid_dependency(tmp_project) -> None:
    prepared = _prepared(
        {
            "web": ServiceSpec(image="nginx:1.27-alpine", depends_on=["missing"]),
        }
    )
    report = await run_preflight(
        stack_name="demo",
        prepared=prepared,
        config_files=None,
        ctx=make_ctx(tmp_project),
        stop_at_first=True,
    )
    assert report.ok is False
    assert report.failure_reason == "invalid_dependency"
    assert report.dependency is not None
    assert report.dependency.valid is False


@pytest.mark.asyncio
async def test_run_preflight_collects_all_issues_when_not_stopping(tmp_project) -> None:
    prepared = _prepared(
        {
            "web": ServiceSpec(image="nginx:1.27-alpine", depends_on=["missing"]),
        }
    )
    report = await run_preflight(
        stack_name="demo",
        prepared=prepared,
        config_files=None,
        ctx=make_ctx(tmp_project),
        stop_at_first=False,
    )
    assert report.ok is False
    assert any(issue.code == "invalid_dependency" for issue in report.issues)

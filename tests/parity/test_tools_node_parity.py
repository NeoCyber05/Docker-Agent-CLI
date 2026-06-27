"""Tools node LangGraph parity — mirrors toolsNode.parity.test.ts."""

from __future__ import annotations

from typing import Any

import pytest

from src.agent import BackendQueryParams
from src.engine.langgraph_backend import LangGraphBackend
from src.types.events import LoopEvent
from src.types.message import UserMessage
from src.types.permissions import AlwaysAllowInSession, Deny
from tests.parity.conftest import fake_provider, output_field, text_done, tool_use_call


def _expect_event_order(events: list[LoopEvent], *types: str) -> None:
    indices = [next(i for i, e in enumerate(events) if e.type == t) for t in types]
    for i in range(len(indices) - 1):
        assert indices[i] >= 0
        assert indices[i] < indices[i + 1]


async def _run_backend(
    ctx: Any,
    tool_name: str,
    input_data: object,
) -> list[LoopEvent]:
    backend = LangGraphBackend()
    events: list[LoopEvent] = []
    async for ev in backend.query(
        BackendQueryParams(
            messages=[UserMessage(content=f"run {tool_name}")],
            ctx=ctx,
            provider=fake_provider([tool_use_call(tool_name, input_data), text_done()]),
        )
    ):
        events.append(ev)
    return events


async def _run_tool_test(
    tmp_project: Any,
    make_context: Any,
    *,
    tool_name: str,
    input_data: object,
    expect_permission_request: bool = False,
) -> tuple[list[LoopEvent], LoopEvent]:
    from pydantic import TypeAdapter

    from src.types.events import LoopEvent as LoopEventType

    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(TypeAdapter(LoopEventType).validate_python(ev))
    )
    events.extend(await _run_backend(ctx, tool_name, input_data))
    types = [e.type for e in events]
    assert "iteration_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    if expect_permission_request:
        assert "permission_request" in types

    tool_result = next((e for e in events if e.type == "tool_result"), None)
    assert tool_result is not None
    return events, tool_result


@pytest.mark.asyncio
async def test_validate_spec(tmp_project, make_context) -> None:
    _, tool_result = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="validate_spec",
        input_data={"services": [{"name": "web", "kind": "custom", "image": "nginx:latest"}]},
    )
    assert output_field(tool_result.output, "valid") is True


@pytest.mark.asyncio
async def test_resolve_dependency(tmp_project, make_context) -> None:
    _, tool_result = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="resolve_dependency",
        input_data={
            "services": [
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:latest",
                    "depends_on": ["db"],
                },
                {"name": "db", "kind": "catalog", "catalogId": "redis:7"},
            ]
        },
    )
    assert output_field(tool_result.output, "valid") is True


@pytest.mark.asyncio
async def test_check_port_conflict(tmp_project, make_context) -> None:
    await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="check_port_conflict",
        input_data={
            "services": [
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:latest",
                    "exposure": "public",
                    "containerPort": 80,
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_list_stacks(tmp_project, make_context) -> None:
    _, tool_result = await _run_tool_test(
        tmp_project, make_context, tool_name="list_stacks", input_data={}
    )
    assert isinstance(output_field(tool_result.output, "stacks"), list)


@pytest.mark.asyncio
async def test_inspect_drift(tmp_project, make_context) -> None:
    await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="inspect_drift",
        input_data={"stackName": "test"},
    )


@pytest.mark.asyncio
async def test_get_stack_status(tmp_project, make_context) -> None:
    _, tool_result = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="get_stack_status",
        input_data={"stackName": "test"},
    )
    assert output_field(tool_result.output, "rows") is not None
    assert output_field(tool_result.output, "log_tail") is not None


@pytest.mark.asyncio
async def test_get_health(tmp_project, make_context) -> None:
    _, tool_result = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="get_health",
        input_data={"stackName": "test"},
    )
    assert output_field(tool_result.output, "containers") is not None


@pytest.mark.asyncio
async def test_get_logs(tmp_project, make_context) -> None:
    await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="get_logs",
        input_data={"stackName": "test"},
    )


@pytest.mark.asyncio
async def test_pull_image(tmp_project, make_context) -> None:
    events, _ = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="pull_image",
        input_data={"image": "nginx:latest"},
        expect_permission_request=True,
    )
    _expect_event_order(events, "permission_request", "tool_call", "tool_result")


@pytest.mark.asyncio
async def test_exec_docker(tmp_project, make_context) -> None:
    events, _ = await _run_tool_test(
        tmp_project,
        make_context,
        tool_name="exec_docker",
        input_data={"args": ["ps"]},
        expect_permission_request=True,
    )
    _expect_event_order(events, "permission_request", "tool_call", "tool_result")


@pytest.mark.asyncio
async def test_permission_denied_no_tool_events(make_context) -> None:
    from pydantic import TypeAdapter

    from src.types.events import LoopEvent as LoopEventType

    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(TypeAdapter(LoopEventType).validate_python(ev)),
        permission_response=Deny(),
    )
    collected = await _run_backend(ctx, "exec_docker", {"args": ["ps"]})
    events.extend(collected)

    types = [e.type for e in events]
    assert "permission_request" in types
    assert "tool_call" not in types
    assert "tool_result" not in types


@pytest.mark.asyncio
async def test_always_allow_in_session_skips_second_permission(make_context) -> None:
    from pydantic import TypeAdapter

    from src.types.events import LoopEvent as LoopEventType

    events: list[LoopEvent] = []
    allow_set: set[str] = set()
    ctx = make_context(
        emit=lambda ev: events.append(TypeAdapter(LoopEventType).validate_python(ev)),
        permission_response=AlwaysAllowInSession(),
        allow_set=allow_set,
    )

    first = await _run_backend(ctx, "exec_docker", {"args": ["ps"]})
    events.extend(first)
    assert "permission_request" in [e.type for e in events]
    assert "exec_docker" in allow_set

    second = await _run_backend(ctx, "exec_docker", {"args": ["ps"]})
    assert "permission_request" not in [e.type for e in second]
    assert "tool_call" in [e.type for e in second]
    assert "tool_result" in [e.type for e in second]


@pytest.mark.asyncio
async def test_internal_apply_stack_no_tool_events(tmp_project, make_context) -> None:
    ctx = make_context()
    events = await _run_backend(ctx, "apply_stack", {"stackName": "test"})
    types = [e.type for e in events]
    assert "tool_call" not in types
    assert "tool_result" not in types
    assert "permission_request" not in types


@pytest.mark.asyncio
async def test_unknown_tool_no_tool_events(tmp_project, make_context) -> None:
    ctx = make_context()
    events = await _run_backend(ctx, "unknown_tool_xyz", {})
    types = [e.type for e in events]
    assert "tool_call" not in types
    assert "tool_result" not in types


@pytest.mark.asyncio
async def test_schema_validation_failure_no_tool_events(tmp_project, make_context) -> None:
    ctx = make_context()
    events = await _run_backend(ctx, "get_health", {})
    types = [e.type for e in events]
    assert "tool_call" not in types
    assert "tool_result" not in types
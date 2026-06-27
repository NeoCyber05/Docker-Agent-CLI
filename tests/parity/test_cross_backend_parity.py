"""Cross-backend parity — mirrors CrossBackendParity.test.ts."""

from __future__ import annotations

import pytest

from src.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from src.types.message import UserMessage
from src.types.permissions import Deny, TypedConfirmValue
from tests.parity.conftest import fake_provider, output_field, text_done, tool_use_call


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_empty_user_end_turn_emits_assistant_text(
    backend_name, make_context, run_backend
) -> None:
    ctx = make_context()
    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="hello")],
        ctx=ctx,
        provider=fake_provider(
            [[TextDeltaEvent(text="hello"), MessageStopEvent(stop_reason="end_turn")]]
        ),
    )
    types = [e.type for e in events]
    assert "assistant_text" in types
    assert "tool_call" not in types
    assert "tool_result" not in types
    assert "error" not in types


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_read_only_tool_call_emits_expected_events(
    backend_name, make_context, run_backend
) -> None:
    ctx = make_context()
    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="list stacks")],
        ctx=ctx,
        provider=fake_provider([tool_use_call("list_stacks", {}), text_done()]),
    )
    types = [e.type for e in events]
    assert "iteration_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "assistant_text" in types

    tool_result = next((e for e in events if e.type == "tool_result"), None)
    assert tool_result is not None
    assert tool_result.name == "list_stacks"
    assert output_field(tool_result.output, "stacks") is not None
    assert isinstance(output_field(tool_result.output, "stacks"), list)


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_permission_denied_emits_permission_request_only(
    backend_name, make_context, run_backend
) -> None:
    collected_events: list[object] = []
    ctx = make_context(emit=lambda ev: collected_events.append(ev), permission_response=Deny())
    backend_events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="pull nginx")],
        ctx=ctx,
        provider=fake_provider(
            [
                tool_use_call("pull_image", {"image": "nginx:latest"}),
                text_done(),
            ]
        ),
    )
    types = [e.type for e in backend_events]
    all_types = types + [
        ev["type"] if isinstance(ev, dict) else getattr(ev, "type", None)
        for ev in collected_events
    ]
    assert "permission_request" in all_types
    assert "tool_call" not in types
    assert "tool_result" not in types


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_max_iterations_emits_error(backend_name, make_context, run_backend) -> None:
    ctx = make_context()
    iteration = [
        ToolUseStartEvent(id="t1", name="list_stacks"),
        ToolUseDeltaEvent(id="t1", args_partial_json="{}"),
        ToolUseStopEvent(id="t1"),
        MessageStopEvent(stop_reason="tool_use"),
    ]
    calls = [list(iteration) for _ in range(25)]

    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="list stacks forever")],
        ctx=ctx,
        provider=fake_provider(calls),
    )

    error_ev = next((e for e in events if e.type == "error"), None)
    assert error_ev is not None
    assert "agent loop reached max iterations" in str(error_ev.error)

    iteration_starts = [e for e in events if e.type == "iteration_start"]
    assert len(iteration_starts) <= 24


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_direct_destroy_all_matching_confirm(backend_name, make_context, run_backend) -> None:
    ctx = make_context(typed_confirm_response=TypedConfirmValue(value="DESTROY ALL"))
    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="destroy all stacks")],
        ctx=ctx,
        provider=fake_provider([]),
    )
    tool_result = next((e for e in events if e.type == "tool_result"), None)
    assert tool_result is not None
    assert tool_result.name == "destroy_all_stacks"
    assert isinstance(output_field(tool_result.output, "destroyed"), list)


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_direct_destroy_all_mismatch_aborts(backend_name, make_context, run_backend) -> None:
    ctx = make_context()
    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="destroy all stacks")],
        ctx=ctx,
        provider=fake_provider([]),
    )
    types = [e.type for e in events]
    assert "tool_call" not in types
    assert "tool_result" not in types
    assert "assistant_text" in types
    assert any(e.type == "assistant_text" and "aborted" in e.delta for e in events)


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_direct_destroy_stack_with_volumes(backend_name, make_context, run_backend) -> None:
    ctx = make_context(typed_confirm_response=TypedConfirmValue(value="DESTROY webapp"))
    events = await run_backend(
        backend_name=backend_name,
        messages=[UserMessage(content="Destroy stack webapp with volumes")],
        ctx=ctx,
        provider=fake_provider([]),
    )
    tool_result = next((e for e in events if e.type == "tool_result"), None)
    assert tool_result is not None
    assert tool_result.name == "destroy_stack"
    assert output_field(tool_result.output, "ok") is True
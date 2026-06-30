"""Cross-backend parity — mirrors CrossBackendParity.test.ts."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from docker_agent.agent import BackendQueryParams, create_backend
from docker_agent.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from docker_agent.types.message import UserMessage
from docker_agent.types.permissions import Deny, TypedConfirmValue
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.parity.conftest import fake_provider, output_field, text_done, tool_use_call


@pytest.mark.parametrize("backend_name", ["current", "langgraph"])
@pytest.mark.asyncio
async def test_backend_writes_assistant_messages_back_to_params(
    backend_name, make_context
) -> None:
    """Regression: backends must persist assistant turns onto params.messages
    so resumed sessions show model output, not just user prompts."""
    ctx = make_context()
    params = BackendQueryParams(
        messages=[UserMessage(content="hello")],
        ctx=ctx,
        provider=fake_provider(
            [[TextDeltaEvent(text="hi back"), MessageStopEvent(stop_reason="end_turn")]]
        ),
    )

    prev = os.environ.get("DOCKER_AGENT_BACKEND")
    os.environ["DOCKER_AGENT_BACKEND"] = backend_name
    try:
        backend = create_backend()
        async for _ in backend.query(params):
            pass
    finally:
        if prev is None:
            os.environ.pop("DOCKER_AGENT_BACKEND", None)
        else:
            os.environ["DOCKER_AGENT_BACKEND"] = prev

    roles = [m.role for m in params.messages]
    assert roles == ["user", "assistant"]


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
        messages=[UserMessage(content="run docker ps")],
        ctx=ctx,
        provider=fake_provider(
            [
                tool_use_call("exec_docker", {"args": ["ps"]}),
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
async def test_max_iterations_emits_graceful_summary(backend_name, make_context, run_backend) -> None:
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
    assert error_ev is None

    graceful = next(
        (
            e
            for e in events
            if e.type == "assistant_text" and "đã dùng hết" in e.delta
        ),
        None,
    )
    assert graceful is not None

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
async def test_direct_destroy_stack_with_volumes(
    backend_name, make_context, run_backend, tmp_project
) -> None:
    from docker_agent.state.state_store import StateStore

    from tests.mocks.mock_compose_runner import MockComposeRunner

    state_store = StateStore(str(tmp_project))
    compose_runner = MockComposeRunner(str(tmp_project))
    state_store.write(
        "webapp",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="webapp",
                createdAt=datetime.now(UTC).isoformat(),
                lastApplied=None,
                intent="test",
                provider="fake",
                generatedBy="test",
                envFileSources={},
            ),
            services={"web": ServiceSpec(image="nginx:1.27")},
        ),
    )
    ctx = make_context(
        typed_confirm_response=TypedConfirmValue(value="DESTROY webapp"),
        state_store=state_store,
        compose_runner=compose_runner,
    )
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
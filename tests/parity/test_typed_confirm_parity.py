"""Typed-confirm LangGraph parity — mirrors typedConfirm.parity.test.ts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from docker_agent.agent import BackendQueryParams
from docker_agent.engine.langgraph_backend import LangGraphBackend
from docker_agent.types.events import LoopEvent
from docker_agent.types.message import UserMessage
from docker_agent.types.permissions import Approve, Deny, TypedConfirmValue
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.parity.conftest import (
    fake_provider,
    output_field,
    patch_langchain_fake_model,
    text_done,
    tool_use_call,
)


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
    events: list[LoopEvent] = []
    backend = LangGraphBackend()
    provider = fake_provider([tool_use_call(tool_name, input_data), text_done()])
    with pytest.MonkeyPatch.context() as mp:
        patch_langchain_fake_model(mp, provider)
        async for ev in backend.query(
            BackendQueryParams(
                messages=[UserMessage(content=f"run {tool_name}")],
                ctx=ctx,
                provider=provider,
            )
        ):
            events.append(ev)
    return events

@pytest.mark.asyncio
async def test_destroy_all_stacks_typed_confirm_match_executes(make_context) -> None:
    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        typed_confirm_response=TypedConfirmValue(value="DESTROY ALL"),
    )
    collected = await _run_backend(ctx, "destroy_all_stacks", {})
    events.extend(collected)

    _expect_event_order(events, "typed_confirm_request", "tool_call", "tool_result")
    tool_result = next(
        (e for e in events if e.type == "tool_result" and e.name == "destroy_all_stacks"),
        None,
    )
    assert tool_result is not None
    assert isinstance(output_field(tool_result.output, "destroyed"), list)


@pytest.mark.asyncio
async def test_destroy_all_stacks_typed_confirm_mismatch_aborts(make_context) -> None:
    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        typed_confirm_response=TypedConfirmValue(value="WRONG"),
    )
    collected = await _run_backend(ctx, "destroy_all_stacks", {})
    events.extend(collected)

    types = [e.type for e in events]
    assert "typed_confirm_request" in types
    assert "tool_call" not in types
    assert "tool_result" not in types


@pytest.mark.asyncio
async def test_destroy_stack_remove_volumes_typed_confirm_match(make_context, tmp_project) -> None:
    from docker_agent.state.state_store import StateStore

    state_store = StateStore(str(tmp_project))
    compose_runner = MockComposeRunner(str(tmp_project))
    state_store.write(
        "test",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="test",
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
    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        typed_confirm_response=TypedConfirmValue(value="DESTROY test"),
        state_store=state_store,
        compose_runner=compose_runner,
    )
    collected = await _run_backend(
        ctx, "destroy_stack", {"stackName": "test", "removeVolumes": True}
    )
    events.extend(collected)

    _expect_event_order(events, "typed_confirm_request", "tool_call", "tool_result")
    tool_result = next(
        (e for e in events if e.type == "tool_result" and e.name == "destroy_stack"),
        None,
    )
    assert tool_result is not None
    assert output_field(tool_result.output, "ok") is True


@pytest.mark.asyncio
async def test_destroy_stack_remove_volumes_typed_confirm_mismatch(make_context) -> None:
    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        typed_confirm_response=TypedConfirmValue(value="x"),
    )
    collected = await _run_backend(
        ctx, "destroy_stack", {"stackName": "test", "removeVolumes": True}
    )
    events.extend(collected)

    types = [e.type for e in events]
    assert "typed_confirm_request" in types
    assert "tool_call" not in types
    assert "tool_result" not in types


@pytest.mark.asyncio
async def test_destroy_stack_without_remove_volumes_permission_gate(make_context) -> None:
    events: list[LoopEvent] = []
    ctx = make_context(emit=lambda ev: events.append(_dict_to_event(ev)))
    collected = await _run_backend(ctx, "destroy_stack", {"stackName": "test"})
    events.extend(collected)

    _expect_event_order(events, "permission_request", "tool_call", "tool_result")
    assert "typed_confirm_request" not in [e.type for e in events]


@pytest.mark.asyncio
async def test_destroy_stack_without_remove_volumes_permission_denied(make_context) -> None:
    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        permission_response=Deny(),
    )
    collected = await _run_backend(ctx, "destroy_stack", {"stackName": "test"})
    events.extend(collected)

    types = [e.type for e in events]
    assert "permission_request" in types
    assert "tool_call" not in types
    assert "tool_result" not in types
    assert "typed_confirm_request" not in types


@pytest.mark.asyncio
async def test_remediate_drift_approval_apply_succeeds(make_context, tmp_project) -> None:
    from docker_agent.state.state_store import StateStore

    state_store = StateStore(str(tmp_project))
    compose_runner = MockComposeRunner(str(tmp_project))
    compose_runner.on_bound_runner_created = lambda runner: runner.set_running_services(["web"])

    state_store.write(
        "test",
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name="test",
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

    events: list[LoopEvent] = []
    ctx = make_context(
        emit=lambda ev: events.append(_dict_to_event(ev)),
        state_store=state_store,
        compose_runner=compose_runner,
        confirm_response=Approve(),
    )
    collected = await _run_backend(ctx, "remediate_drift", {"stackName": "test"})
    events.extend(collected)

    types = [e.type for e in events]
    assert "permission_request" in types
    assert "plan_ready" not in types
    _expect_event_order(events, "permission_request", "tool_call", "tool_result")

    remediate_result = next(
        (e for e in events if e.type == "tool_result" and e.name == "remediate_drift"),
        None,
    )
    assert remediate_result is not None
    assert output_field(remediate_result.output, "remediable") is True

def _dict_to_event(ev: dict[str, Any]) -> LoopEvent:
    from pydantic import TypeAdapter

    return TypeAdapter(LoopEvent).validate_python(ev)

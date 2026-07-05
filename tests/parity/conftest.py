"""Shared helpers for backend parity tests."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from docker_agent.agent import BackendQueryParams, create_backend
from docker_agent.core.loop_context import PlanReadyPayload
from docker_agent.services.api.types import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from docker_agent.state.state_store import StateStore
from docker_agent.types.events import LoopEvent
from docker_agent.types.message import Message
from docker_agent.types.permissions import (
    AlwaysAllowInSession,
    Approve,
    Deny,
    PermissionResponse,
    TypedConfirmValue,
)
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def _nanoid() -> str:
    return secrets.token_urlsafe(16)


def fake_provider(calls: list[list[Any]]):
    class _Provider:
        name = "fake"

        def __init__(self, scripted_calls: list[list[Any]]) -> None:
            self.calls = scripted_calls
            self._call_idx = 0

        async def stream(self, _params: object) -> AsyncIterator[Any]:
            events = (
                self.calls[self._call_idx]
                if self._call_idx < len(self.calls)
                else []
            )
            self._call_idx += 1
            for ev in events:
                yield ev

    return _Provider(calls)


class _ParityLangChainModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, *, tool_choice: object = None, **kwargs: object):
        del tool_choice, kwargs
        object.__setattr__(self, "bound_tools", tools)
        return self


def _event_value(event: object, field: str) -> object:
    if isinstance(event, dict):
        return event.get(field)
    return getattr(event, field, None)


def _event_args_delta(event: object) -> str:
    if isinstance(event, dict):
        return str(event.get("args_partial_json") or event.get("argsPartialJson") or "")
    return str(getattr(event, "args_partial_json", "") or "")


def _provider_events_to_ai_message(events: list[Any]) -> AIMessage:
    content: list[str] = []
    tool_order: list[str] = []
    tool_calls_by_id: dict[str, dict[str, object]] = {}

    for event in events:
        event_type = _event_value(event, "type")
        if event_type == "text_delta":
            content.append(str(_event_value(event, "text") or ""))
            continue
        if event_type == "tool_use_start":
            call_id = str(_event_value(event, "id") or f"tool-{len(tool_order) + 1}")
            tool_order.append(call_id)
            tool_calls_by_id[call_id] = {
                "id": call_id,
                "name": str(_event_value(event, "name") or ""),
                "args_json": "",
            }
            continue
        if event_type == "tool_use_delta":
            call_id = str(_event_value(event, "id") or f"tool-{len(tool_order) + 1}")
            tool_call = tool_calls_by_id.setdefault(
                call_id,
                {"id": call_id, "name": "", "args_json": ""},
            )
            tool_call["args_json"] = str(tool_call["args_json"]) + _event_args_delta(
                event
            )

    tool_calls: list[dict[str, object]] = []
    for call_id in tool_order:
        tool_call = tool_calls_by_id[call_id]
        raw_args = str(tool_call.get("args_json") or "")
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(
            {
                "id": call_id,
                "name": str(tool_call.get("name") or ""),
                "args": args,
            }
        )

    return AIMessage(content="".join(content), tool_calls=tool_calls)


def patch_langchain_fake_model(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
) -> _ParityLangChainModel:
    responses = [
        _provider_events_to_ai_message(events)
        for events in getattr(provider, "calls", [])
    ]
    if responses and responses[-1].tool_calls:
        responses.append(AIMessage(content="done"))
    model = _ParityLangChainModel(responses=responses or [AIMessage(content="")])
    monkeypatch.setattr(
        "docker_agent.engine.langgraph.runtime.create_chat_model",
        lambda **_kwargs: model,
    )
    return model

def tool_use_call(tool_name: str, input_data: object) -> list[Any]:
    return [
        ToolUseStartEvent(id="t1", name=tool_name),
        ToolUseDeltaEvent(id="t1", args_partial_json=json.dumps(input_data)),
        ToolUseStopEvent(id="t1"),
        MessageStopEvent(stop_reason="tool_use"),
    ]


def text_done(text: str = "done") -> list[Any]:
    return [
        TextDeltaEvent(text=text),
        MessageStopEvent(stop_reason="end_turn"),
    ]


class _ParityLoopContext:
    """Concrete LoopContext for parity tests with mock Docker/Compose."""

    def __init__(
        self,
        *,
        cwd: str,
        state_store: StateStore,
        docker_engine: MockDockerEngine,
        compose_runner: MockComposeRunner,
        abort_signal: asyncio.Event,
        request_permission: Any,
        request_confirm: Any,
        request_typed_confirm: Any,
        request_secrets_input: Any,
        allow_set: set[str],
    ) -> None:
        self.cwd = cwd
        self.state_store = state_store
        self.docker_engine = docker_engine
        self.compose_runner = compose_runner
        self.abort_signal = abort_signal
        self.image_validator = None
        self.session_id = None
        self.health_check_deadline_ms = None
        self.request_permission = request_permission
        self.request_confirm = request_confirm
        self.request_typed_confirm = request_typed_confirm
        self.request_secrets_input = request_secrets_input
        self.allow_set = allow_set
        self.logger = None


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "project-policies.yaml").write_text("project: {}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def make_context(tmp_project: Path):
    def _make(**opts: Any) -> _ParityLoopContext:
        emit = opts.get("emit")

        async def request_permission(tool: str, input_data: object) -> PermissionResponse:
            if emit is not None:
                emit(
                    {
                        "type": "permission_request",
                        "id": _nanoid(),
                        "tool": tool,
                        "input": input_data,
                    }
                )
            return opts.get("permission_response", Approve())

        async def request_confirm(plan: PlanReadyPayload | dict[str, Any]) -> PermissionResponse:
            if not isinstance(plan, PlanReadyPayload):
                plan = PlanReadyPayload.model_validate(plan)
            if emit is not None:
                payload: dict[str, Any] = {
                    "type": "plan_ready",
                    "id": _nanoid(),
                    "composeYaml": plan.compose_yaml,
                    "diff": plan.diff.model_dump(by_alias=True),
                }
                if plan.auto_generated_secrets is not None:
                    payload["autoGeneratedSecrets"] = plan.auto_generated_secrets
                if plan.config_files is not None:
                    payload["configFiles"] = plan.config_files
                emit(payload)
            return opts.get("confirm_response", Approve())

        async def request_typed_confirm(phrase: str, reason: str) -> PermissionResponse:
            if emit is not None:
                emit(
                    {
                        "type": "typed_confirm_request",
                        "id": _nanoid(),
                        "phrase": phrase,
                        "reason": reason,
                    }
                )
            return opts.get("typed_confirm_response", TypedConfirmValue(value="x"))

        async def request_secrets_input(
            _service: str, _keys: list[str], _reason: str
        ) -> PermissionResponse:
            return opts.get("secrets_response", Deny())

        return _ParityLoopContext(
            cwd=str(tmp_project),
            state_store=opts.get("state_store") or StateStore(str(tmp_project)),
            docker_engine=MockDockerEngine(),
            compose_runner=opts.get("compose_runner") or MockComposeRunner(str(tmp_project)),
            abort_signal=asyncio.Event(),
            request_permission=opts.get("request_permission") or request_permission,
            request_confirm=opts.get("request_confirm") or request_confirm,
            request_typed_confirm=opts.get("request_typed_confirm") or request_typed_confirm,
            request_secrets_input=opts.get("request_secrets_input") or request_secrets_input,
            allow_set=opts.get("allow_set", set()),
        )

    return _make


@pytest.fixture
def run_backend(monkeypatch: pytest.MonkeyPatch):
    async def _run(
        *,
        backend_name: str,
        messages: list[Message],
        ctx: _ParityLoopContext,
        provider: Any,
    ) -> list[LoopEvent]:
        prev = os.environ.get("DOCKER_AGENT_BACKEND")
        prev_mcp = os.environ.get("DOCKER_AGENT_MCP")
        os.environ["DOCKER_AGENT_BACKEND"] = backend_name
        if backend_name == "langgraph":
            os.environ["DOCKER_AGENT_MCP"] = "0"
        try:
            if backend_name == "langgraph":
                patch_langchain_fake_model(monkeypatch, provider)
            backend = create_backend()
            events: list[LoopEvent] = []
            async for ev in backend.query(
                BackendQueryParams(messages=messages, ctx=ctx, provider=provider)
            ):
                events.append(ev)
            return events
        finally:
            if prev is None:
                os.environ.pop("DOCKER_AGENT_BACKEND", None)
            else:
                os.environ["DOCKER_AGENT_BACKEND"] = prev
            if prev_mcp is None:
                os.environ.pop("DOCKER_AGENT_MCP", None)
            else:
                os.environ["DOCKER_AGENT_MCP"] = prev_mcp

    return _run


def output_field(output: object, field: str) -> object:
    if isinstance(output, dict):
        return output.get(field)
    return getattr(output, field, None)


__all__ = [
    "AlwaysAllowInSession",
    "Approve",
    "Deny",
    "TypedConfirmValue",
    "fake_provider",
    "output_field",
    "patch_langchain_fake_model",
    "text_done",
    "tool_use_call",
]

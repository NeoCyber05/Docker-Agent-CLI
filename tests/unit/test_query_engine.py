"""Parity tests for QueryEngine â€” mirrors src/__tests__/QueryEngine.test.ts."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from docker_agent.query_engine import QueryEngine, restore_session_from_record
from docker_agent.services.api.types import CallModelParams, ProviderEvent
from docker_agent.state.session_store import SessionStore
from docker_agent.state.state_store import StateStore
from docker_agent.types.permissions import Approve
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from docker_agent.vault.api_key_store import MemoryApiKeyStore
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def fake_provider(events: list[ProviderEvent | dict[str, Any]]):
    class _Provider:
        name = "fake"

        async def stream(self, _params: CallModelParams):
            for ev in events:
                yield ev

    return _Provider()


def recording_provider(
    events: list[ProviderEvent | dict[str, Any]], calls: list[CallModelParams]
):
    class _Provider:
        name = "recording"

        async def stream(self, params: CallModelParams):
            calls.append(params)
            for ev in events:
                yield ev

    return _Provider()


@pytest.fixture(autouse=True)
def use_current_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """QueryEngine unit tests target CurrentBackend semantics (TS default)."""
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "current")


def make_engine(tmp_project, **kwargs: Any) -> QueryEngine:
    policy_file = tmp_project / "project-policies.yaml"
    if not policy_file.exists():
        policy_file.write_text("project: {}\n", encoding="utf-8")
    state_root = kwargs.pop("state_root", tmp_project / ".docker-agent")
    state_store = StateStore(str(state_root))
    return QueryEngine(
        cwd=str(tmp_project),
        state_store=state_store,
        docker_engine=kwargs.pop("docker_engine", MockDockerEngine()),
        compose_runner=kwargs.pop("compose_runner", MockComposeRunner(str(tmp_project))),
        provider=kwargs.pop("provider", fake_provider([])),
        model=kwargs.get("model"),
        session_store=kwargs.get("session_store"),
        health_check_deadline_ms=kwargs.get("health_check_deadline_ms"),
    )


@pytest.mark.asyncio
async def test_query_is_reusable_across_multiple_turns(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "first"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )

    turn1: list[str] = []
    async for ev in engine.query("hi"):
        if ev.type == "assistant_text":
            turn1.append(ev.delta)
    assert "".join(turn1) == "first"

    engine.provider = fake_provider(
        [
            {"type": "text_delta", "text": "second"},
            {"type": "message_stop", "stop_reason": "end_turn"},
        ]
    )

    turn2: list[str] = []
    async for ev in engine.query("again"):
        if ev.type == "assistant_text":
            turn2.append(ev.delta)
    assert "".join(turn2) == "second"


@pytest.mark.asyncio
async def test_respond_to_resolves_pending_permission_request(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "tool_use_start", "id": "t1", "name": "destroy_stack"},
                {
                    "type": "tool_use_delta",
                    "id": "t1",
                    "args_partial_json": '{"stackName":"ghost"}',
                },
                {"type": "tool_use_stop", "id": "t1"},
                {"type": "message_stop", "stop_reason": "tool_use"},
            ]
        ),
    )

    collected: list[str] = []

    async def drain() -> None:
        async for ev in engine.query("destroy ghost"):
            if ev.type == "permission_request":
                engine.respond_to(ev.id, Approve())
            collected.append(ev.type)

    await drain()
    assert "permission_request" in collected
    assert "tool_result" in collected


def test_respond_to_returns_false_for_unknown_id(tmp_project) -> None:
    engine = make_engine(tmp_project)
    assert engine.respond_to("nonexistent", Approve()) is False


@pytest.mark.asyncio
async def test_passes_active_model_override_to_provider(tmp_project) -> None:
    calls: list[CallModelParams] = []
    engine = make_engine(
        tmp_project,
        provider=recording_provider(
            [
                {"type": "text_delta", "text": "ok"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ],
            calls,
        ),
        model="gpt-4.1-mini",
    )

    async for _ in engine.query("hello"):
        pass

    assert len(calls) == 1
    assert calls[0].model == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_abort_marks_active_controller_as_aborted(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "hello"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )

    gen = engine.query("test")
    first = await gen.__anext__()
    assert first.type in ("iteration_start", "assistant_text")
    ctrl = engine._active_controller
    assert ctrl is not None
    engine.abort()
    assert ctrl.is_set()
    async for _ in gen:
        pass


@pytest.mark.asyncio
async def test_passes_active_abort_signal_to_provider(tmp_project) -> None:
    calls: list[CallModelParams] = []
    engine = make_engine(
        tmp_project,
        provider=recording_provider(
            [{"type": "message_stop", "stop_reason": "end_turn"}],
            calls,
        ),
    )

    async for _ in engine.query("hello"):
        pass

    assert calls[0].signal is not None
    assert isinstance(calls[0].signal, asyncio.Event)


@pytest.mark.asyncio
async def test_abort_resolves_pending_permission_and_ends_turn(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "tool_use_start", "id": "t1", "name": "destroy_stack"},
                {
                    "type": "tool_use_delta",
                    "id": "t1",
                    "args_partial_json": '{"stackName":"ghost"}',
                },
                {"type": "tool_use_stop", "id": "t1"},
                {"type": "message_stop", "stop_reason": "tool_use"},
            ]
        ),
    )

    seen: list[str] = []

    async def drain() -> None:
        async for event in engine.query("destroy ghost"):
            seen.append(event.type)
            if event.type == "permission_request":
                engine.abort()

    done = asyncio.create_task(drain())
    result = await asyncio.wait_for(done, timeout=1.0)
    assert result is None
    assert "permission_request" in seen


@pytest.mark.asyncio
async def test_each_query_gets_fresh_abort_controller(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "first"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )

    async for _ in engine.query("turn1"):
        pass
    assert engine._active_controller is None

    engine.provider = fake_provider(
        [
            {"type": "text_delta", "text": "second"},
            {"type": "message_stop", "stop_reason": "end_turn"},
        ]
    )
    events: list[str] = []
    async for ev in engine.query("turn2"):
        if ev.type == "assistant_text":
            events.append(ev.delta)
    assert "".join(events) == "second"


def test_load_session_restores_model_and_returns_cwd_mismatch_warning(tmp_project) -> None:
    state_store = StateStore(str(tmp_project / ".docker-agent"))
    engine = QueryEngine(
        cwd="/current",
        state_store=state_store,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
        provider=fake_provider([]),
        model="cli-default",
    )

    warning = engine.load_session(
        {
            "schema_version": 1,
            "id": "saved-session",
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-02T00:00:00.000Z",
            "cwd": "/saved",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "first_prompt": "hello",
            "stack_names": [],
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert warning is not None
    assert "/saved" in warning
    assert engine.session_id == "saved-session"
    assert engine.model == "gpt-4.1-mini"
    assert engine.is_resumed is True


def test_restore_session_from_record_restores_provider(tmp_project) -> None:
    state_store = StateStore(str(tmp_project / ".docker-agent"))
    engine = QueryEngine(
        cwd=str(tmp_project),
        state_store=state_store,
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
        provider=fake_provider([]),
        model=None,
    )
    record = {
        "schema_version": 1,
        "id": "saved-session",
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-02T00:00:00.000Z",
        "cwd": str(tmp_project),
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "first_prompt": "hello",
        "stack_names": [],
        "messages": [{"role": "user", "content": "hello"}],
    }
    restore_session_from_record(
        engine=engine,
        record=record,
        api_key_store=MemoryApiKeyStore(initial={"openai": "sk-test"}),
    )
    assert getattr(engine.provider, "name", None) == "openai"
    assert engine.model == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_persists_created_at_model_and_stack_names_across_turns(tmp_project) -> None:
    state_root = tmp_project / "state"
    state_store = StateStore(str(state_root))
    session_store = SessionStore(str(state_root))
    stack_def = StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name="web",
            createdAt="2026-01-01T00:00:00.000Z",
            lastApplied=None,
            intent="test",
            provider="gemini",
            generatedBy="test",
            envFileSources={},
        ),
        services={"app": ServiceSpec(image="nginx")},
    )
    engine = make_engine(
        tmp_project,
        state_root=state_root,
        session_store=session_store,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "ok"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
        model="gemini-2.0",
    )
    state_store.write("web", stack_def)

    async for _ in engine.query("deploy"):
        pass

    session_id = engine.session_id
    after_first = session_store.read(session_id)
    assert after_first is not None
    created_at = after_first["created_at"]
    assert created_at

    engine.provider = fake_provider(
        [
            {"type": "text_delta", "text": "again"},
            {"type": "message_stop", "stop_reason": "end_turn"},
        ]
    )
    async for _ in engine.query("update"):
        pass

    saved = session_store.read(session_id)
    assert saved is not None
    assert saved.get("model") == "gemini-2.0"
    assert saved.get("stack_names") == ["web"]
    assert saved.get("resources") == [
        {"server": "docker", "type": "stack", "name": "web"}
    ]
    assert saved.get("created_at") == created_at
    assert saved.get("updated_at") != created_at


@pytest.mark.asyncio
async def test_turn_accumulates_and_persists_assistant_messages(tmp_project) -> None:
    """Regression: assistant output must survive a turn so resume shows it."""
    state_root = tmp_project / "state"
    session_store = SessionStore(str(state_root))
    engine = make_engine(
        tmp_project,
        state_root=state_root,
        session_store=session_store,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "hello there"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )

    async for _ in engine.query("hi"):
        pass

    messages = engine.get_messages()
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant"]

    saved = session_store.read(engine.session_id)
    assert saved is not None
    saved_roles = [m["role"] for m in saved["messages"]]
    assert "assistant" in saved_roles
    assistant = next(m for m in saved["messages"] if m["role"] == "assistant")
    assert any(
        block.get("type") == "text" and block.get("text") == "hello there"
        for block in assistant["content"]
    )


@pytest.mark.asyncio
async def test_reset_clears_messages_and_allow_set(tmp_project) -> None:
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "text_delta", "text": "hello"},
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )
    async for _ in engine.query("test"):
        pass
    engine.reset()
    assert engine.get_messages() == []


@pytest.mark.asyncio
async def test_turn_start_log_redacts_secrets_in_message(tmp_project) -> None:
    from docker_agent.state.logger import StructuredLogger

    log_dir = tmp_project / ".docker-agent" / "logs"
    logger = StructuredLogger(str(log_dir), "sess-log")
    engine = make_engine(
        tmp_project,
        provider=fake_provider(
            [
                {"type": "message_stop", "stop_reason": "end_turn"},
            ]
        ),
    )
    engine.set_logger(logger)
    async for _ in engine.query("API_KEY=sk-live-xxxx"):
        pass
    logger.close()

    log_file = log_dir / "sess-log.ndjson"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "sk-live-xxxx" not in content
    row = json.loads(content.strip().splitlines()[0])
    assert row["category"] == "turn_start"
    assert "API_KEY=***" in row["message"]

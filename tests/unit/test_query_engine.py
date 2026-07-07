"""QueryEngine core-session tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from infra_agent.agent import BackendQueryParams
from infra_agent.query_engine import QueryEngine, restore_session_from_record
from infra_agent.state.session_store import SessionStore
from infra_agent.types.events import AssistantText, ToolResult
from infra_agent.types.message import AssistantBlock, AssistantMessage
from infra_agent.types.message import UserMessage
from infra_agent.types.permissions import Approve
from infra_agent.vault.api_key_store import MemoryApiKeyStore


class FakeProvider:
    name = "fake"

    def list_models(self) -> None:
        return None


class YieldBackend:
    name = "fake-backend"

    def __init__(self, events: list[Any], resources: list[dict[str, Any]] | None = None) -> None:
        self.events = events
        self.resources = resources or []
        self.calls: list[BackendQueryParams] = []

    async def query(self, params: BackendQueryParams) -> AsyncIterator[Any]:
        self.calls.append(params)
        if self.resources:
            params.ctx.resources = list(self.resources)
        for event in self.events:
            if isinstance(event, str):
                params.messages.append(
                    AssistantMessage(
                        content=[AssistantBlock.model_validate({"type": "text", "text": event})]
                    )
                )
                yield AssistantText(delta=event)
            else:
                yield event


class PermissionBackend:
    name = "permission-backend"

    async def query(self, params: BackendQueryParams) -> AsyncIterator[Any]:
        response = await params.ctx.request_permission("docker.destroy_stack", {"stack": "web"})
        yield ToolResult(
            name="docker.destroy_stack",
            output={"decision": getattr(response, "kind", None) or response.get("kind")},
        )


def fake_provider() -> FakeProvider:
    return FakeProvider()


def install_backend(monkeypatch: pytest.MonkeyPatch, backend: Any) -> Any:
    monkeypatch.setattr("infra_agent.query_engine.create_backend", lambda: backend)
    return backend


def make_engine(tmp_project, **kwargs: Any) -> QueryEngine:
    return QueryEngine(
        cwd=str(tmp_project),
        provider=kwargs.get("provider", fake_provider()),
        model=kwargs.get("model"),
        session_store=kwargs.get("session_store"),
    )


@pytest.mark.asyncio
async def test_query_is_reusable_across_multiple_turns(tmp_project, monkeypatch) -> None:
    backend = install_backend(monkeypatch, YieldBackend(["first"]))
    engine = make_engine(tmp_project)

    turn1: list[str] = []
    async for ev in engine.query("hi"):
        if ev.type == "assistant_text":
            turn1.append(ev.delta)
    assert "".join(turn1) == "first"

    backend.events = ["second"]
    turn2: list[str] = []
    async for ev in engine.query("again"):
        if ev.type == "assistant_text":
            turn2.append(ev.delta)
    assert "".join(turn2) == "second"
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_respond_to_resolves_pending_permission_request(tmp_project, monkeypatch) -> None:
    install_backend(monkeypatch, PermissionBackend())
    engine = make_engine(tmp_project)
    collected: list[str] = []

    async for ev in engine.query("destroy web"):
        if ev.type == "permission_request":
            engine.respond_to(ev.id, Approve())
        collected.append(ev.type)

    assert "permission_request" in collected
    assert "tool_result" in collected


def test_respond_to_returns_false_for_unknown_id(tmp_project) -> None:
    engine = make_engine(tmp_project)
    assert engine.respond_to("nonexistent", Approve()) is False


@pytest.mark.asyncio
async def test_backend_receives_active_model_override(tmp_project, monkeypatch) -> None:
    backend = install_backend(monkeypatch, YieldBackend(["ok"]))
    engine = make_engine(tmp_project, model="gpt-4.1-mini")

    async for _ in engine.query("hello"):
        pass

    assert len(backend.calls) == 1
    assert backend.calls[0].model == "gpt-4.1-mini"
    assert backend.calls[0].ctx.model == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_abort_marks_active_controller_as_aborted(tmp_project, monkeypatch) -> None:
    install_backend(monkeypatch, YieldBackend(["hello"]))
    engine = make_engine(tmp_project)

    gen = engine.query("test")
    first = await gen.__anext__()
    assert first.type == "assistant_text"
    ctrl = engine._active_controller
    assert ctrl is not None
    engine.abort()
    assert ctrl.is_set()
    async for _ in gen:
        pass


@pytest.mark.asyncio
async def test_abort_resolves_pending_permission_and_ends_turn(tmp_project, monkeypatch) -> None:
    install_backend(monkeypatch, PermissionBackend())
    engine = make_engine(tmp_project)
    seen: list[str] = []

    async for event in engine.query("destroy web"):
        seen.append(event.type)
        if event.type == "permission_request":
            engine.abort()

    assert "permission_request" in seen


@pytest.mark.asyncio
async def test_each_query_gets_fresh_abort_controller(tmp_project, monkeypatch) -> None:
    backend = install_backend(monkeypatch, YieldBackend(["first"]))
    engine = make_engine(tmp_project)

    async for _ in engine.query("turn1"):
        pass
    assert engine._active_controller is None

    backend.events = ["second"]
    events: list[str] = []
    async for ev in engine.query("turn2"):
        if ev.type == "assistant_text":
            events.append(ev.delta)
    assert "".join(events) == "second"


def test_load_session_restores_model_and_returns_cwd_mismatch_warning(tmp_project) -> None:
    engine = QueryEngine(
        cwd="/current",
        provider=fake_provider(),
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
    engine = QueryEngine(
        cwd=str(tmp_project),
        provider=fake_provider(),
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
async def test_persists_created_at_model_and_resources_across_turns(
    tmp_project, monkeypatch
) -> None:
    state_root = tmp_project / "state"
    session_store = SessionStore(str(state_root))
    backend = install_backend(
        monkeypatch,
        YieldBackend(
            ["ok"],
            resources=[{"server": "k8s", "type": "deployment", "name": "web"}],
        ),
    )
    engine = make_engine(
        tmp_project,
        session_store=session_store,
        model="gemini-2.0",
    )

    async for _ in engine.query("deploy"):
        pass

    session_id = engine.session_id
    after_first = session_store.read(session_id)
    assert after_first is not None
    created_at = after_first["created_at"]
    assert created_at

    backend.events = ["again"]
    async for _ in engine.query("update"):
        pass

    saved = session_store.read(session_id)
    assert saved is not None
    assert saved.get("model") == "gemini-2.0"
    assert saved.get("stack_names") == ["web"]
    assert saved.get("resources") == [{"server": "k8s", "type": "deployment", "name": "web"}]
    assert saved.get("created_at") == created_at
    assert saved.get("updated_at") != created_at


@pytest.mark.asyncio
async def test_turn_accumulates_and_persists_assistant_messages(tmp_project, monkeypatch) -> None:
    state_root = tmp_project / "state"
    session_store = SessionStore(str(state_root))
    install_backend(monkeypatch, YieldBackend(["hello there"]))
    engine = make_engine(tmp_project, session_store=session_store)

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


def test_persist_session_saves_snapshot_without_new_turn(tmp_project) -> None:
    state_root = tmp_project / "state"
    session_store = SessionStore(str(state_root))
    engine = make_engine(tmp_project, session_store=session_store)
    engine._messages = [UserMessage(content="resume me")]  # type: ignore[attr-defined]
    engine.persist_session()

    saved = session_store.read(engine.session_id)
    assert saved is not None
    assert saved["first_prompt"] == "resume me"
    assert saved["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_reset_clears_messages_and_allow_set(tmp_project, monkeypatch) -> None:
    install_backend(monkeypatch, YieldBackend(["hello"]))
    engine = make_engine(tmp_project)
    async for _ in engine.query("test"):
        pass
    engine.reset()
    assert engine.get_messages() == []


@pytest.mark.asyncio
async def test_turn_start_log_redacts_secrets_in_message(tmp_project, monkeypatch) -> None:
    from infra_agent.state.logger import StructuredLogger

    log_dir = tmp_project / ".docker-agent" / "logs"
    logger = StructuredLogger(str(log_dir), "sess-log")
    install_backend(monkeypatch, YieldBackend([]))
    engine = make_engine(tmp_project)
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

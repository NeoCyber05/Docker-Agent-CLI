"""Tests for apply_slash_effects."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from docker_agent.screens.apply_slash_effects import SlashEffectApplierDeps, apply_slash_effects
from docker_agent.screens.use_interaction_session import InteractionSession
from docker_agent.vault.api_key_store import MemoryApiKeyStore


def make_deps(**overrides: object) -> SlashEffectApplierDeps:
    engine = MagicMock()
    engine.get_messages.return_value = []
    engine.provider = MagicMock()
    engine.model = None
    session = InteractionSession(engine)  # type: ignore[arg-type]
    deps = SlashEffectApplierDeps(
        input="/test",
        session=session,
        engine=engine,
        api_key_store=MemoryApiKeyStore(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


@pytest.mark.asyncio
async def test_emit_user_text() -> None:
    deps = make_deps()
    await apply_slash_effects([{"type": "emit_user_text", "text": "hello"}], deps)
    assert any(item.type == "text" and item.text == "hello" for item in deps.session.activities)


@pytest.mark.asyncio
async def test_emit_assistant_text() -> None:
    deps = make_deps()
    await apply_slash_effects([{"type": "emit_assistant_text", "delta": "world"}], deps)
    assert any(
        item.type == "text" and item.role == "assistant" and item.text == "world"
        for item in deps.session.activities
    )


@pytest.mark.asyncio
async def test_emit_error() -> None:
    deps = make_deps()
    await apply_slash_effects([{"type": "emit_error", "message": "boom"}], deps)
    assert any(item.type == "text" and item.role == "error" for item in deps.session.activities)


@pytest.mark.asyncio
async def test_submit_prompt() -> None:
    deps = make_deps()
    await apply_slash_effects([{"type": "submit_prompt", "prompt": "deploy"}], deps)
    assert deps.session.interaction.current == "deploy"


@pytest.mark.asyncio
async def test_exit_effect() -> None:
    exit_fn = MagicMock()
    stop_log = MagicMock()
    deps = make_deps(exit=exit_fn, stop_log_pane=stop_log)
    await apply_slash_effects([{"type": "exit"}], deps)
    exit_fn.assert_called_once()
    stop_log.assert_called_once()


@pytest.mark.asyncio
async def test_clear_session() -> None:
    timeline_calls: list[int] = []
    deps = make_deps(
        set_show_details=MagicMock(),
        set_show_palette=MagicMock(),
        set_show_queue=MagicMock(),
        set_timeline_key=timeline_calls.append,
        stop_log_pane=MagicMock(),
    )
    deps.session.dispatch_activity({"type": "user_text", "text": "old"})
    await apply_slash_effects([{"type": "clear_session"}], deps)
    assert deps.session.activities == []
    assert timeline_calls == [0]


@pytest.mark.asyncio
async def test_open_provider_connect() -> None:
    open_connect = AsyncMock()
    deps = make_deps(open_provider_connect=open_connect)
    await apply_slash_effects([{"type": "open_provider_connect"}], deps)
    open_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_model_picker() -> None:
    open_picker = AsyncMock()
    deps = make_deps(open_model_picker=open_picker)
    await apply_slash_effects(
        [{"type": "open_model_picker", "scope_provider": "openai"}], deps
    )
    open_picker.assert_awaited_once_with("openai")


@pytest.mark.asyncio
async def test_open_session_picker() -> None:
    open_picker = AsyncMock()
    deps = make_deps(open_session_picker=open_picker)
    await apply_slash_effects([{"type": "open_session_picker"}], deps)
    open_picker.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_model(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(config_path))
    set_provider = MagicMock()
    set_model = MagicMock()
    deps = make_deps(
        set_active_provider_name=set_provider,
        set_active_model=set_model,
    )
    await apply_slash_effects(
        [{"type": "set_model", "provider": "openai", "model": "gpt-4o"}],
        deps,
    )
    assert deps.engine.model == "gpt-4o"
    assert getattr(deps.engine.provider, "name", None) == "openai"
    set_provider.assert_called_once_with("openai")
    set_model.assert_called_once_with("gpt-4o")
    from docker_agent.config import load_user_config

    saved = load_user_config(config_path)
    assert saved.provider == "openai"
    assert saved.model == "gpt-4o"


@pytest.mark.asyncio
async def test_load_session_without_store() -> None:
    deps = make_deps(session_store=None)
    await apply_slash_effects([{"type": "load_session"}], deps)
    assert any(item.type == "text" and item.role == "error" for item in deps.session.activities)


@pytest.mark.asyncio
async def test_load_session_with_store() -> None:
    store = MagicMock()
    record = {
        "schema_version": 1,
        "id": "sess-1",
        "messages": [],
        "provider": "openrouter",
        "model": "gpt-4o-mini",
    }
    store.latest.return_value = record
    engine = MagicMock()
    engine.get_messages.return_value = []
    session = InteractionSession(engine)
    set_model = MagicMock()
    set_provider = MagicMock()
    deps = SlashEffectApplierDeps(
        input="/resume",
        session=session,
        engine=engine,
        api_key_store=MemoryApiKeyStore(),
        session_store=store,
        set_active_model=set_model,
        set_active_provider_name=set_provider,
    )
    with pytest.MonkeyPatch.context() as mp:
        restore = MagicMock(return_value="warning")
        import importlib

        slash_effects_mod = importlib.import_module(
            "docker_agent.screens.apply_slash_effects"
        )
        mp.setattr(slash_effects_mod, "restore_session_from_record", restore)
        await apply_slash_effects([{"type": "load_session"}], deps)
    restore.assert_called_once_with(
        engine=engine,
        record=record,
        api_key_store=deps.api_key_store,
    )
    set_provider.assert_called_once_with("openrouter")
    set_model.assert_called_once_with("gpt-4o-mini")
    engine.get_messages.assert_called()


@pytest.mark.asyncio
async def test_start_log_pane() -> None:
    start_log = MagicMock()
    deps = make_deps(start_log_pane=start_log)
    await apply_slash_effects(
        [{"type": "start_log_pane", "stack_name": "web", "service": "api"}],
        deps,
    )
    start_log.assert_called_once_with("web", "api")
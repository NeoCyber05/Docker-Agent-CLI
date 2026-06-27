"""Apply slash command effects to the REPL session.

Parity: ``src/screens/applySlashEffects.ts``.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from src.query_engine import QueryEngine
from src.screens.use_interaction_session import InteractionSession
from src.services.api import resolve_provider_for_request
from src.slash_router import (
    ClearSession,
    EmitAssistantText,
    EmitError,
    EmitUserText,
    ExitEffect,
    LoadSession,
    OpenModelPicker,
    OpenProviderConnect,
    SetModel,
    SlashEffect,
    StartLogPane,
    SubmitPrompt,
)
from src.state.session_store import SessionStore
from src.vault.api_key_store import ApiKeyStore


@dataclass
class SlashEffectApplierDeps:
    input: str
    session: InteractionSession
    engine: QueryEngine
    api_key_store: ApiKeyStore
    session_store: SessionStore | None = None
    exit: Callable[[], None] | None = None
    stop_log_pane: Callable[[], None] | None = None
    set_show_details: Callable[[bool], None] | None = None
    set_show_palette: Callable[[bool], None] | None = None
    set_show_queue: Callable[[bool], None] | None = None
    set_timeline_key: Callable[[int], None] | None = None
    set_active_provider_name: Callable[[str], None] | None = None
    set_active_model: Callable[[str | None], None] | None = None
    open_provider_connect: Callable[[], Awaitable[None]] | None = None
    open_model_picker: Callable[[str | None], Awaitable[None]] | None = None
    start_log_pane: Callable[[str, str | None], None] | None = None


async def apply_slash_effects(
    effects: list[SlashEffect],
    deps: SlashEffectApplierDeps,
) -> None:
    for effect in effects:
        effect_type = effect["type"]
        if effect_type == "emit_user_text":
            user_effect = cast(EmitUserText, effect)
            deps.session.dispatch_activity(
                {"type": "user_text", "text": user_effect["text"]}
            )
        elif effect_type == "emit_assistant_text":
            assistant_effect = cast(EmitAssistantText, effect)
            deps.session.dispatch_activity(
                {"type": "assistant_text", "delta": assistant_effect["delta"]}
            )
        elif effect_type == "emit_error":
            error_effect = cast(EmitError, effect)
            deps.session.dispatch_activity(
                {"type": "error", "error": RuntimeError(error_effect["message"])}
            )
        elif effect_type == "submit_prompt":
            prompt_effect = cast(SubmitPrompt, effect)
            deps.session.submit(prompt_effect["prompt"])
        elif effect_type == "exit":
            deps.session.cancel_current()
            if deps.stop_log_pane is not None:
                deps.stop_log_pane()
            if deps.exit is not None:
                deps.exit()
            _ = cast(ExitEffect, effect)
        elif effect_type == "clear_session":
            if deps.stop_log_pane is not None:
                deps.stop_log_pane()
            if deps.set_show_details is not None:
                deps.set_show_details(False)
            if deps.set_show_palette is not None:
                deps.set_show_palette(False)
            if deps.set_show_queue is not None:
                deps.set_show_queue(False)
            deps.session.reset()
            if deps.set_timeline_key is not None:
                deps.set_timeline_key(0)
            _ = cast(ClearSession, effect)
        elif effect_type == "open_provider_connect":
            if deps.open_provider_connect is not None:
                await deps.open_provider_connect()
            _ = cast(OpenProviderConnect, effect)
        elif effect_type == "open_model_picker":
            picker_effect = cast(OpenModelPicker, effect)
            if deps.open_model_picker is not None:
                await deps.open_model_picker(picker_effect.get("scope_provider"))
        elif effect_type == "set_model":
            model_effect = cast(SetModel, effect)
            deps.engine.provider = resolve_provider_for_request(
                model_effect["provider"],
                os.environ,
                api_key_store=deps.api_key_store,
            )
            deps.engine.model = model_effect["model"]
            if deps.set_active_provider_name is not None:
                deps.set_active_provider_name(model_effect["provider"])
            if deps.set_active_model is not None:
                deps.set_active_model(model_effect["model"])
        elif effect_type == "load_session":
            load_effect = cast(LoadSession, effect)
            store = deps.session_store
            if store is None:
                deps.session.dispatch_activity(
                    {"type": "user_text", "text": deps.input}
                )
                deps.session.dispatch_activity(
                    {
                        "type": "error",
                        "error": RuntimeError("Session persistence not configured."),
                    }
                )
                continue
            session_id = load_effect.get("session_id")
            record = store.read(session_id) if session_id else store.latest()
            if record is None:
                deps.session.dispatch_activity(
                    {"type": "user_text", "text": deps.input}
                )
                message = (
                    f'Session "{session_id}" not found.'
                    if session_id
                    else "No previous session found to resume."
                )
                deps.session.dispatch_activity(
                    {"type": "error", "error": RuntimeError(message)}
                )
                continue
            warning = deps.engine.load_session(record)
            if warning:
                deps.session.dispatch_activity(
                    {"type": "assistant_text", "delta": warning}
                )
            if record.get("model") is not None and deps.set_active_model is not None:
                deps.set_active_model(record["model"])
            deps.session.replace_activities(deps.engine.get_messages())
        elif effect_type == "start_log_pane" and deps.start_log_pane is not None:
            log_effect = cast(StartLogPane, effect)
            deps.start_log_pane(log_effect["stack_name"], log_effect.get("service"))


__all__ = ["SlashEffectApplierDeps", "apply_slash_effects"]
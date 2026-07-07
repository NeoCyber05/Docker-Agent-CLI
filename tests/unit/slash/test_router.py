"""Parity tests for slash router â€” mirrors src/__tests__/slashRouter.test.ts."""

from __future__ import annotations

import pytest

from infra_agent.slash.router import (
    SLASH_COMMAND_DEFS,
    SlashRouterContext,
    resolve_slash_key,
    route_slash_command,
)
from infra_agent.state.session_store import SessionStore
from infra_agent.vault.api_key_store import MemoryApiKeyStore


def make_ctx(tmp_project) -> SlashRouterContext:
    return SlashRouterContext(
        cwd=str(tmp_project),
        active_provider_name="gemini",
        api_key_store=MemoryApiKeyStore(),
    )


def test_resolve_slash_key_single_token_commands() -> None:
    assert resolve_slash_key(["/help"]) == "/help"
    assert resolve_slash_key(["/stacks"]) == "/stacks"


def test_resolve_slash_key_multi_token_longest_match() -> None:
    assert resolve_slash_key(["/destroy", "all"]) == "/destroy all"
    assert resolve_slash_key(["/destroy", "ALL"]) == "/destroy all"


def test_resolve_slash_key_unknown_command() -> None:
    assert resolve_slash_key(["/not-a-command"]) is None


@pytest.mark.asyncio
async def test_unknown_command_emits_error(tmp_project) -> None:
    result = await route_slash_command("/nope", make_ctx(tmp_project))
    assert result.handled is True
    assert {"type": "emit_user_text", "text": "/nope"} in result.effects
    assert any(
        effect["type"] == "emit_error"
        and effect["message"] == "Unknown slash command: /nope. Try /help."
        for effect in result.effects
    )


def test_registry_metadata_covers_every_slash_command_def() -> None:
    assert len(SLASH_COMMAND_DEFS) >= 12
    for definition in SLASH_COMMAND_DEFS:
        assert definition.usage.startswith("/")
        assert definition.description
        assert definition.insert_text.startswith("/")


@pytest.mark.asyncio
async def test_help_emits_formatted_help(tmp_project) -> None:
    result = await route_slash_command("/help", make_ctx(tmp_project))
    assert {"type": "emit_user_text", "text": "/help"} in result.effects
    assistant = next(effect for effect in result.effects if effect["type"] == "emit_assistant_text")
    assert "Supported slash commands" in assistant["delta"]
    assert "Keyboard shortcuts" in assistant["delta"]
    assert "Ctrl+O" in assistant["delta"]


@pytest.mark.asyncio
async def test_stacks_emits_table_without_llm_submit(tmp_project) -> None:
    result = await route_slash_command("/stacks", make_ctx(tmp_project))
    assert result.handled is True
    assert not any(effect["type"] == "submit_prompt" for effect in result.effects)
    assistant = next(effect for effect in result.effects if effect["type"] == "emit_assistant_text")
    assert "List managed Docker stacks" in assistant["delta"]


@pytest.mark.asyncio
async def test_yaml_requires_stack_arg(tmp_project) -> None:
    result = await route_slash_command("/yaml", make_ctx(tmp_project))
    assert {"type": "emit_user_text", "text": "/yaml"} in result.effects
    assert {"type": "emit_error", "message": "Usage: /yaml <stack>"} in result.effects


@pytest.mark.asyncio
async def test_yaml_emits_plugin_prompt_guidance(tmp_project) -> None:
    result = await route_slash_command("/yaml webapp", make_ctx(tmp_project))
    assistant = next(effect for effect in result.effects if effect["type"] == "emit_assistant_text")
    assert "Show YAML for stack webapp" in assistant["delta"]


@pytest.mark.asyncio
async def test_status_rewrites_to_agent_prompt(tmp_project) -> None:
    result = await route_slash_command("/status webapp", make_ctx(tmp_project))
    assert result.handled is True
    assert result.effects == [
        {"type": "emit_user_text", "text": "/status webapp"},
        {"type": "submit_prompt", "prompt": "Show status and drift for stack webapp"},
    ]


@pytest.mark.asyncio
async def test_status_without_arg_shows_usage_error(tmp_project) -> None:
    result = await route_slash_command("/status", make_ctx(tmp_project))
    assert any(
        effect["type"] == "emit_error" and effect["message"] == "Usage: /status <stack>"
        for effect in result.effects
    )


@pytest.mark.asyncio
async def test_stop_stack_rewrites_to_stop_prompt(tmp_project) -> None:
    result = await route_slash_command("/stop webapp", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/stop webapp"},
        {"type": "submit_prompt", "prompt": "Stop stack webapp"},
    ]


@pytest.mark.asyncio
async def test_stop_stack_with_services_rewrites_to_stop_prompt(tmp_project) -> None:
    result = await route_slash_command("/stop webapp api web", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/stop webapp api web"},
        {"type": "submit_prompt", "prompt": "Stop stack webapp services api, web"},
    ]


@pytest.mark.asyncio
async def test_stop_without_arg_shows_usage_error(tmp_project) -> None:
    result = await route_slash_command("/stop", make_ctx(tmp_project))
    assert any(
        effect["type"] == "emit_error"
        and effect["message"] == "Usage: /stop <stack> [service...]"
        for effect in result.effects
    )


@pytest.mark.asyncio
async def test_destroy_all_rewrites_case_insensitively(tmp_project) -> None:
    result = await route_slash_command("/destroy ALL", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/destroy ALL"},
        {"type": "submit_prompt", "prompt": "Destroy all stacks"},
    ]


@pytest.mark.asyncio
async def test_destroy_stack_rewrites_to_destroy_prompt(tmp_project) -> None:
    result = await route_slash_command("/destroy webapp", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/destroy webapp"},
        {"type": "submit_prompt", "prompt": "Destroy stack webapp"},
    ]


@pytest.mark.asyncio
async def test_destroy_without_arg_shows_usage_error(tmp_project) -> None:
    result = await route_slash_command("/destroy", make_ctx(tmp_project))
    assert any(
        effect["type"] == "emit_error" and effect["message"] == "Usage: /destroy <stack>"
        for effect in result.effects
    )


@pytest.mark.asyncio
async def test_exit_emits_exit_effect(tmp_project) -> None:
    result = await route_slash_command("/exit", make_ctx(tmp_project))
    assert result.effects == [{"type": "exit"}]


@pytest.mark.asyncio
async def test_clear_emits_clear_session_effect(tmp_project) -> None:
    result = await route_slash_command("/clear", make_ctx(tmp_project))
    assert result.effects == [{"type": "clear_session"}]


@pytest.mark.asyncio
async def test_connect_opens_provider_connect_dialog(tmp_project) -> None:
    result = await route_slash_command("/connect", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/connect"},
        {"type": "open_provider_connect"},
    ]


@pytest.mark.asyncio
async def test_model_without_arg_opens_picker(tmp_project) -> None:
    result = await route_slash_command("/model", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/model"},
        {"type": "open_model_picker"},
    ]


@pytest.mark.asyncio
async def test_model_with_valid_provider_model_emits_set_model(tmp_project) -> None:
    result = await route_slash_command("/model openai/gpt-4.1-mini", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "emit_user_text", "text": "/model openai/gpt-4.1-mini"},
        {"type": "set_model", "provider": "openai", "model": "gpt-4.1-mini"},
        {"type": "emit_assistant_text", "delta": "Model set to gpt-4.1-mini (openai)"},
    ]


@pytest.mark.asyncio
async def test_model_with_invalid_arg_emits_error(tmp_project) -> None:
    result = await route_slash_command("/model !!!", make_ctx(tmp_project))
    assert any(effect["type"] == "emit_error" for effect in result.effects)


@pytest.mark.asyncio
async def test_logs_requires_stack(tmp_project) -> None:
    result = await route_slash_command("/logs", make_ctx(tmp_project))
    assert any(
        effect["type"] == "emit_error" and "Usage:" in effect["message"]
        for effect in result.effects
    )


@pytest.mark.asyncio
async def test_logs_emits_start_log_pane(tmp_project) -> None:
    result = await route_slash_command("/logs webapp api", make_ctx(tmp_project))
    assert result.effects == [
        {"type": "start_log_pane", "stack_name": "webapp", "service": "api"},
    ]


@pytest.mark.asyncio
async def test_log_alias_emits_start_log_pane(tmp_project) -> None:
    result = await route_slash_command("/log webapp", make_ctx(tmp_project))
    assert result.effects == [{"type": "start_log_pane", "stack_name": "webapp"}]


@pytest.mark.asyncio
async def test_resume_emits_open_session_picker(tmp_project) -> None:
    ctx = make_ctx(tmp_project)
    session_store = SessionStore(str(tmp_project / ".docker-agent"))
    result = await route_slash_command(
        "/resume",
        SlashRouterContext(
            cwd=ctx.cwd,
            active_provider_name=ctx.active_provider_name,
            api_key_store=ctx.api_key_store,
            session_store=session_store,
        ),
    )
    assert result.effects == [
        {"type": "emit_user_text", "text": "/resume"},
        {"type": "open_session_picker"},
    ]


@pytest.mark.asyncio
async def test_resume_rejects_session_id_argument(tmp_project) -> None:
    ctx = make_ctx(tmp_project)
    session_store = SessionStore(str(tmp_project / ".docker-agent"))
    result = await route_slash_command(
        "/resume abc123",
        SlashRouterContext(
            cwd=ctx.cwd,
            active_provider_name=ctx.active_provider_name,
            api_key_store=ctx.api_key_store,
            session_store=session_store,
        ),
    )
    assert {"type": "emit_user_text", "text": "/resume abc123"} in result.effects
    error = next(effect for effect in result.effects if effect["type"] == "emit_error")
    assert "Usage: /resume" in error["message"]

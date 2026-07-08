"""Slash command router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from infra_agent.config import ProviderName
from infra_agent.services.model_catalog import parse_provider_model
from infra_agent.slash.dispatch import (
    SlashDispatchContext,
    destroy_stack_prompt,
    dispatch_stacks,
    dispatch_yaml,
    stop_stack_prompt,
)
from infra_agent.state.session_store import SessionStore
from infra_agent.vault.api_key_store import ApiKeyStore


@dataclass
class SlashCommandDef:
    usage: str
    description: str
    insert_text: str


class EmitUserText(TypedDict):
    type: Literal["emit_user_text"]
    text: str


class EmitAssistantText(TypedDict):
    type: Literal["emit_assistant_text"]
    delta: str


class EmitError(TypedDict):
    type: Literal["emit_error"]
    message: str


class SubmitPrompt(TypedDict):
    type: Literal["submit_prompt"]
    prompt: str


class ExitEffect(TypedDict):
    type: Literal["exit"]


class ClearSession(TypedDict):
    type: Literal["clear_session"]


class OpenProviderConnect(TypedDict):
    type: Literal["open_provider_connect"]


class OpenModelPicker(TypedDict, total=False):
    type: Literal["open_model_picker"]
    scope_provider: ProviderName


class SetModel(TypedDict):
    type: Literal["set_model"]
    provider: ProviderName
    model: str


class LoadSession(TypedDict, total=False):
    type: Literal["load_session"]
    session_id: str


class OpenSessionPicker(TypedDict):
    type: Literal["open_session_picker"]


class StartLogPane(TypedDict, total=False):
    type: Literal["start_log_pane"]
    stack_name: str
    service: str


SlashEffect = (
    EmitUserText
    | EmitAssistantText
    | EmitError
    | SubmitPrompt
    | ExitEffect
    | ClearSession
    | OpenProviderConnect
    | OpenModelPicker
    | SetModel
    | LoadSession
    | OpenSessionPicker
    | StartLogPane
)


@dataclass
class SlashRouteResult:
    handled: bool
    effects: list[SlashEffect]


@dataclass
class SlashRouterContext:
    cwd: str
    active_provider_name: ProviderName
    api_key_store: ApiKeyStore
    session_store: SessionStore | None = None


SLASH_COMMAND_DEFS: tuple[SlashCommandDef, ...] = (
    SlashCommandDef("/help", "Show slash command help", "/help"),
    SlashCommandDef("/clear", "Clear chat history and session state", "/clear"),
    SlashCommandDef("/exit", "Exit docker-agent", "/exit"),
    SlashCommandDef("/stacks", "List managed stacks", "/stacks"),
    SlashCommandDef(
        "/status <stack>", "Show status and drift for a stack", "/status "
    ),
    SlashCommandDef(
        "/logs <stack> [service]",
        "Live-tail a stack's logs (Esc to stop)",
        "/logs ",
    ),
    SlashCommandDef(
        "/stop <stack> [service...]",
        "Stop stack containers without removing them",
        "/stop ",
    ),
    SlashCommandDef("/destroy <stack>", "Destroy one stack", "/destroy "),
    SlashCommandDef(
        "/destroy all", "Destroy every stack after confirmation", "/destroy all"
    ),
    SlashCommandDef(
        "/connect", "Connect a provider (API key or Ollama)", "/connect"
    ),
    SlashCommandDef(
        "/model",
        "Browse models (no args) or set override (/model provider/id)",
        "/model ",
    ),
    SlashCommandDef("/yaml <stack>", "Show stack YAML", "/yaml "),
    SlashCommandDef(
        "/resume", "List saved sessions and pick one to resume", "/resume"
    ),
)

HANDLER_KEYS = [
    "/destroy all",
    "/help",
    "/clear",
    "/exit",
    "/stacks",
    "/status",
    "/logs",
    "/stop",
    "/destroy",
    "/connect",
    "/model",
    "/yaml",
    "/resume",
]

HandlerKey = str


def format_keyboard_shortcuts() -> str:
    return "\n".join(
        [
            "Keyboard shortcuts:",
            "- Ctrl+C: Cancel current turn",
            "- Ctrl+O: Tool details panel",
            "- Ctrl+P: Command palette",
            "- Ctrl+Q: Queue panel (r resume, d remove, c clear)",
            "- Enter (empty, queue paused): Resume queue",
        ]
    )


def format_slash_help() -> str:
    return "\n".join(
        [
            "Supported slash commands:",
            *[f"- {cmd.usage}: {cmd.description}" for cmd in SLASH_COMMAND_DEFS],
            "",
            format_keyboard_shortcuts(),
        ]
    )


def _dispatch_ctx(ctx: SlashRouterContext) -> SlashDispatchContext:
    return SlashDispatchContext(cwd=ctx.cwd)


def resolve_slash_key(parts: list[str]) -> HandlerKey | None:
    lowered = [part.lower() for part in parts]
    aliases = {"/log": "/logs"}
    if lowered and lowered[0] in aliases:
        lowered[0] = aliases[lowered[0]]
    for length in range(min(3, len(lowered)), 0, -1):
        candidate = " ".join(lowered[:length])
        if candidate in HANDLER_KEYS:
            return candidate
    return None


async def route_slash_command(
    input_text: str, ctx: SlashRouterContext
) -> SlashRouteResult:
    parts = input_text.strip().split()
    key = resolve_slash_key(parts)
    if key is None:
        cmd = parts[0].lower() if parts else input_text
        return SlashRouteResult(
            handled=True,
            effects=[
                {"type": "emit_user_text", "text": input_text},
                {
                    "type": "emit_error",
                    "message": f"Unknown slash command: {cmd}. Try /help.",
                },
            ],
        )

    match key:
        case "/help":
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {"type": "emit_assistant_text", "delta": format_slash_help()},
                ],
            )
        case "/clear":
            return SlashRouteResult(handled=True, effects=[{"type": "clear_session"}])
        case "/exit":
            return SlashRouteResult(handled=True, effects=[{"type": "exit"}])
        case "/stacks":
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "emit_assistant_text",
                        "delta": dispatch_stacks(_dispatch_ctx(ctx)),
                    },
                ],
            )
        case "/yaml":
            stack_name = " ".join(parts[1:]).strip()
            if not stack_name:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {"type": "emit_error", "message": "Usage: /yaml <stack>"},
                    ],
                )
            result = dispatch_yaml(stack_name, _dispatch_ctx(ctx))
            if not result["ok"]:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {"type": "emit_error", "message": result["error"]},
                    ],
                )
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {"type": "emit_assistant_text", "delta": result["text"]},
                ],
            )
        case "/status":
            stack_name = " ".join(parts[1:]).strip()
            if not stack_name:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {"type": "emit_error", "message": "Usage: /status <stack>"},
                    ],
                )
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "submit_prompt",
                        "prompt": f"Show status and drift for stack {stack_name}",
                    },
                ],
            )
        case "/stop":
            stop_parts = [part for part in parts[1:] if part]
            if not stop_parts:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {
                            "type": "emit_error",
                            "message": "Usage: /stop <stack> [service...]",
                        },
                    ],
                )
            stack_name = stop_parts[0]
            services = stop_parts[1:] if len(stop_parts) > 1 else None
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "submit_prompt",
                        "prompt": stop_stack_prompt(stack_name, services),
                    },
                ],
            )
        case "/destroy all":
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {"type": "submit_prompt", "prompt": "Destroy all stacks"},
                ],
            )
        case "/destroy":
            arg = " ".join(parts[1:]).strip()
            if not arg:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {"type": "emit_error", "message": "Usage: /destroy <stack>"},
                    ],
                )
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "submit_prompt",
                        "prompt": destroy_stack_prompt(arg),
                    },
                ],
            )
        case "/connect":
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {"type": "open_provider_connect"},
                ],
            )
        case "/model":
            model_arg = " ".join(parts[1:]).strip()
            if not model_arg:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {"type": "open_model_picker"},
                    ],
                )
            parsed = parse_provider_model(model_arg, ctx.active_provider_name)
            if parsed is None or not any(ch.isalnum() for ch in str(parsed["model"])):
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {
                            "type": "emit_error",
                            "message": (
                                "Invalid model. Use /model <id> or "
                                "/model <provider>/<id>"
                            ),
                        },
                    ],
                )
            provider = parsed["provider"]
            model = parsed["model"]
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "set_model",
                        "provider": provider,  # type: ignore[typeddict-item]
                        "model": model,
                    },
                    {
                        "type": "emit_assistant_text",
                        "delta": f"Model set to {model} ({provider})",
                    },
                ],
            )
        case "/resume":
            if len(parts) > 1:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {
                            "type": "emit_error",
                            "message": "Usage: /resume (pick from the session list)",
                        },
                    ],
                )
            if ctx.session_store is None:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {
                            "type": "emit_error",
                            "message": "Session persistence not configured.",
                        },
                    ],
                )
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {"type": "open_session_picker"},
                ],
            )
        case "/logs":
            log_parts = [part for part in parts[1:] if part]
            log_stack = log_parts[0] if log_parts else None
            log_service = log_parts[1] if len(log_parts) > 1 else None
            if not log_stack:
                return SlashRouteResult(
                    handled=True,
                    effects=[
                        {"type": "emit_user_text", "text": input_text},
                        {
                            "type": "emit_error",
                            "message": "Usage: /logs <stack> [service]",
                        },
                    ],
                )
            effect_log: StartLogPane = {
                "type": "start_log_pane",
                "stack_name": log_stack,
            }
            if log_service:
                effect_log["service"] = log_service
            return SlashRouteResult(handled=True, effects=[effect_log])
        case _:
            return SlashRouteResult(
                handled=True,
                effects=[
                    {"type": "emit_user_text", "text": input_text},
                    {
                        "type": "emit_error",
                        "message": f"Unknown slash command: {key}. Try /help.",
                    },
                ],
            )


__all__ = [
    "SlashCommandDef",
    "SlashEffect",
    "SlashRouteResult",
    "SlashRouterContext",
    "SLASH_COMMAND_DEFS",
    "format_keyboard_shortcuts",
    "format_slash_help",
    "resolve_slash_key",
    "route_slash_command",
]



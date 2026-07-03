"""Slash command system - routing, dispatch, and autocomplete."""

from docker_agent.slash.commands import SLASH_COMMANDS, get_slash_command_suggestions
from docker_agent.slash.dispatch import (
    is_destroy_all_prompt,
    parse_direct_destroy_stack,
    parse_direct_stop_stack,
    stop_stack_prompt,
)
from docker_agent.slash.router import (
    HANDLER_KEYS,
    SLASH_COMMAND_DEFS,
    SlashCommandDef,
    SlashRouterContext,
    route_slash_command,
)

__all__ = [
    "HANDLER_KEYS",
    "SLASH_COMMAND_DEFS",
    "SLASH_COMMANDS",
    "SlashCommandDef",
    "SlashRouterContext",
    "get_slash_command_suggestions",
    "is_destroy_all_prompt",
    "parse_direct_destroy_stack",
    "parse_direct_stop_stack",
    "stop_stack_prompt",
    "route_slash_command",
]
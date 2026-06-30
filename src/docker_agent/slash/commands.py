"""Slash command autocomplete suggestions.

Parity: ``src/slashCommands.ts``.
"""

from __future__ import annotations

from docker_agent.slash.router import SLASH_COMMAND_DEFS, SlashCommandDef

SLASH_COMMANDS: tuple[SlashCommandDef, ...] = SLASH_COMMAND_DEFS


def get_slash_command_suggestions(text: str) -> list[SlashCommandDef]:
    query = text.lstrip().lower()
    if not query.startswith("/") or "\n" in query or query.endswith(" "):
        return []
    return [
        command
        for command in SLASH_COMMANDS
        if command.usage.lower().startswith(query)
        or command.insert_text.rstrip().lower().startswith(query)
    ]


__all__ = ["SLASH_COMMANDS", "get_slash_command_suggestions"]
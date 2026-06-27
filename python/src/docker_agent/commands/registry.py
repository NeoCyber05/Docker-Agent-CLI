"""Command palette registry.

Parity: ``src/commands/registry.ts``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docker_agent.slash_router import SLASH_COMMAND_DEFS


@dataclass
class Command:
    id: str
    title: str
    description: str
    shortcut: str | None = None
    action: Callable[[], None] | None = None
    insert_text: str | None = None


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: list[Command] = []

    def register(self, command: Command) -> None:
        index = next(
            (idx for idx, existing in enumerate(self._commands) if existing.id == command.id),
            -1,
        )
        if index == -1:
            self._commands.append(command)
        else:
            self._commands[index] = command

    def get_all(self) -> list[Command]:
        return list(self._commands)

    def find_by_shortcut(self, shortcut: str) -> Command | None:
        return next((cmd for cmd in self._commands if cmd.shortcut == shortcut), None)

    def find_by_id(self, command_id: str) -> Command | None:
        return next((cmd for cmd in self._commands if cmd.id == command_id), None)


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for command in SLASH_COMMAND_DEFS:
        command_id = (
            command.usage[1:]
            .replace("<", "")
            .replace(">", "")
            .replace(" ", "-")
        )
        command_id = "".join(ch.lower() if ch.isalnum() or ch == "-" else "" for ch in command_id)
        registry.register(
            Command(
                id=command_id,
                title=command.usage,
                description=command.description,
                insert_text=command.insert_text,
            )
        )
    return registry


__all__ = ["Command", "CommandRegistry", "create_default_registry"]
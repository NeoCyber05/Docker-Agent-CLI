"""Command palette modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from docker_agent.commands.registry import Command


class CommandPalette(ModalScreen[Command | None]):
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "close", "Close"),
    ]

    def __init__(self, commands: list[Command], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._commands = commands
        self._selected = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="command-palette"):
            yield Static("Command Palette", classes="title")
            yield Static("", id="command-list")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        lines = []
        for index, command in enumerate(self._commands):
            marker = ">" if index == self._selected else " "
            shortcut = f" ({command.shortcut})" if command.shortcut else ""
            lines.append(f"{marker} {command.title} {command.description}{shortcut}")
        self.query_one("#command-list", Static).update("\n".join(lines))

    def action_cursor_up(self) -> None:
        if self._commands:
            self._selected = 0 if self._selected <= 0 else self._selected - 1
            self._refresh()

    def action_cursor_down(self) -> None:
        if self._commands:
            self._selected = (self._selected + 1) % len(self._commands)
            self._refresh()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter" and self._commands:
            self.dismiss(self._commands[self._selected])
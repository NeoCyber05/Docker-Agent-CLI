"""Inline permission prompt shown above the chat input."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from infra_agent.types.permissions import (
    AlwaysAllowInSession,
    Approve,
    Deny,
    PermissionResponse,
)
from infra_agent.ui.tool_presentation import present_tool


class PermissionAnswered(Message):
    """Posted when the user approves, denies, or always-allows a tool."""

    def __init__(self, response: PermissionResponse) -> None:
        super().__init__()
        self.response = response


class PermissionDialog(Static):
    """Inline permission prompt (y/n/a) mounted above the chat input."""

    DEFAULT_CSS = """
    PermissionDialog {
        height: auto;
        max-height: 12;
        overflow-y: auto;
        border-top: solid $accent;
        padding: 0 1;
        background: $surface;
    }
    """

    can_focus = True

    def __init__(
        self,
        tool: str,
        input: Any = None,
        input_data: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._tool = tool
        self._input = input if input is not None else input_data
        self._answered = False
        self._update_content()

    def _append_key_hints(self, content: Text) -> None:
        content.append("  [y] approve  ", style="green")
        content.append("[n] deny  ", style="red")
        content.append("[a] always for this session\n", style="cyan")

    def _update_content(self) -> None:
        presentation = present_tool(self._tool, self._input)
        content = Text()
        content.append("⚠ Permission required\n", style="bold yellow")
        self._append_key_hints(content)
        content.append("\n")
        if presentation.summary:
            content.append(f"  {presentation.summary}\n", style="bold")
        lines = presentation.detail_lines[:8] or [presentation.title]
        for line in lines:
            content.append(f"  {line}\n", style="dim")
        self.update(content)

    def on_mount(self) -> None:
        self.focus()

    def answer(self, response: PermissionResponse) -> None:
        if self._answered:
            return
        self._answered = True
        self.post_message(PermissionAnswered(response))

    def on_key(self, event: Key) -> None:
        if self._answered:
            return
        key = event.key.lower()
        if key == "y":
            self.answer(Approve())
            event.stop()
        elif key == "n":
            self.answer(Deny())
            event.stop()
        elif key == "a":
            self.answer(AlwaysAllowInSession())
            event.stop()

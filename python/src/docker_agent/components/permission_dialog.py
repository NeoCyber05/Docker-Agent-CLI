"""Permission approval modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from docker_agent.types.permissions import (
    AlwaysAllowInSession,
    Approve,
    Deny,
    PermissionResponse,
)
from docker_agent.ui.tool_presentation import present_tool


class PermissionDialog(ModalScreen[PermissionResponse]):
    """Modal screen for y/n/a permission responses."""

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

    def compose(self) -> ComposeResult:
        presentation = present_tool(self._tool, self._input)
        with Vertical(id="permission-dialog"):
            yield Static("Permission required", classes="title")
            yield Static(presentation.title, classes="tool-title")
            yield Static(presentation.summary, classes="dim")
            for line in presentation.detail_lines[:8]:
                yield Static(line, classes="dim")
            yield Static("[y] approve [n] deny [a] always for this session", classes="hint")

    def on_key(self, event: Key) -> None:
        if self._answered:
            return
        key = event.key.lower()
        if key == "y":
            self._answered = True
            self.dismiss(Approve())
        elif key == "n":
            self._answered = True
            self.dismiss(Deny())
        elif key == "a":
            self._answered = True
            self.dismiss(AlwaysAllowInSession())
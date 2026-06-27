"""Live log pane modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

MAX_VISIBLE_LINES = 200


class LogPane(ModalScreen[None]):
    def __init__(
        self,
        stack_name: str,
        lines: list[str] | None = None,
        service: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._stack_name = stack_name
        self._service = service
        self._lines = lines or []

    def compose(self) -> ComposeResult:
        title = (
            f"Live logs: {self._stack_name} / {self._service}"
            if self._service
            else f"Live logs: {self._stack_name}"
        )
        with Vertical(id="log-pane"):
            yield Static(title, classes="title")
            yield RichLog(id="log-output", highlight=True, markup=True)
            yield Static("Esc to stop", classes="dim")

    def on_mount(self) -> None:
        log = self.query_one("#log-output", RichLog)
        visible = self._lines[-MAX_VISIBLE_LINES:]
        if not visible:
            log.write("no running containers / waiting for output...", shrink=False)
        else:
            for line in visible:
                log.write(line.rstrip("\n"), shrink=False)

    def append_line(self, line: str) -> None:
        self.query_one("#log-output", RichLog).write(line.rstrip("\n"), shrink=False)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
"""Queue management modal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static


@dataclass
class QueueAction:
    kind: str
    index: int | None = None


class QueuePanel(ModalScreen[QueueAction | None]):
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "close", "Close"),
    ]

    def __init__(
        self,
        queue: list[str],
        on_remove: Callable[[int], None] | None = None,
        on_clear: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._queue = list(queue)
        self._selected = 0
        self._on_remove = on_remove
        self._on_clear = on_clear
        self._on_resume = on_resume

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-panel"):
            yield Static(f"Queue ({len(self._queue)})", classes="title")
            yield Static("", id="queue-list")
            yield Static(
                "Up/Down select | r resume | d remove | c clear | Esc close",
                classes="dim",
            )

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        if not self._queue:
            self.query_one("#queue-list", Static).update("Empty")
            return
        if self._selected >= len(self._queue):
            self._selected = max(0, len(self._queue) - 1)
        lines = []
        for index, item in enumerate(self._queue):
            marker = ">" if index == self._selected else " "
            lines.append(f"{marker} {index + 1}. {item}")
        self.query_one("#queue-list", Static).update("\n".join(lines))

    def action_cursor_up(self) -> None:
        if self._queue:
            self._selected = 0 if self._selected <= 0 else self._selected - 1
            self._refresh()

    def action_cursor_down(self) -> None:
        if self._queue:
            self._selected = (self._selected + 1) % len(self._queue)
            self._refresh()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        if key == "d" and self._queue:
            if self._on_remove:
                self._on_remove(self._selected)
            self._queue.pop(self._selected)
            self._refresh()
            self.dismiss(QueueAction(kind="remove", index=self._selected))
        elif key == "c":
            if self._on_clear:
                self._on_clear()
            self._queue.clear()
            self._refresh()
            self.dismiss(QueueAction(kind="clear"))
        elif key == "r" and self._queue:
            if self._on_resume:
                self._on_resume()
            self.dismiss(QueueAction(kind="resume"))
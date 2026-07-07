"""Session picker inline panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from infra_agent.state.session_store import SessionIndexEntry

PAGE_SIZE = 10


@dataclass
class SessionChoice:
    session_id: str


class SessionPickerClosed(Message):
    """Posted when the inline session picker is dismissed."""

    def __init__(self, result: SessionChoice | None) -> None:
        super().__init__()
        self.result = result


def _format_entry_line(entry: SessionIndexEntry) -> str:
    prompt = entry["first_prompt"]
    if len(prompt) > 56:
        prompt = prompt[:53] + "..."
    stacks = f"  [{', '.join(entry['stack_names'])}]" if entry["stack_names"] else ""
    return f"{entry['id']}{stacks}  {prompt}"


class SessionPickerDialog(Vertical):
    """Inline session picker rendered inside the REPL."""

    can_focus = True

    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    SessionPickerDialog {
        height: auto;
        max-height: 16;
        border: round cyan;
        padding: 0 1;
        margin: 1 0;
    }

    SessionPickerDialog .title {
        text-style: bold;
    }

    SessionPickerDialog .hint {
        color: $text-muted;
    }
    """

    def __init__(self, entries: list[SessionIndexEntry], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entries = entries
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="session-picker-dialog"):
            yield Static("Select session to resume", classes="title")
            yield Static("", id="session-list")
            yield Static(
                "[↑/↓] navigate [Enter] select [Esc] cancel",
                classes="hint",
            )

    def on_mount(self) -> None:
        self._refresh_list()
        self.call_after_refresh(self.focus)

    def _refresh_list(self) -> None:
        if self._entries:
            self._index = min(self._index, len(self._entries) - 1)
        else:
            self._index = 0

        start = min(
            max(0, self._index - PAGE_SIZE // 2),
            max(0, len(self._entries) - PAGE_SIZE),
        )
        visible = self._entries[start : start + PAGE_SIZE]

        lines: list[str] = []
        if start > 0:
            lines.append(" ↑ more…")
        for offset, entry in enumerate(visible):
            absolute = start + offset
            prefix = "❯ " if absolute == self._index else "  "
            lines.append(f"{prefix}{_format_entry_line(entry)}")
        if start + PAGE_SIZE < len(self._entries):
            lines.append(" ↓ more…")

        self.query_one("#session-list", Static).update(
            "\n".join(lines) or "No saved sessions."
        )

    def _close(self, result: SessionChoice | None) -> None:
        self.post_message(SessionPickerClosed(result))

    def action_cursor_up(self) -> None:
        if self._entries:
            self._index = (self._index - 1) % len(self._entries)
            self._refresh_list()

    def action_cursor_down(self) -> None:
        if self._entries:
            self._index = (self._index + 1) % len(self._entries)
            self._refresh_list()

    def action_cancel(self) -> None:
        self._close(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            if not self._entries:
                return
            entry = self._entries[self._index]
            self._close(SessionChoice(session_id=entry["id"]))
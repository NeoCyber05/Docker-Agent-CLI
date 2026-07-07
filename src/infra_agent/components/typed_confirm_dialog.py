"""Confirmation dialogs for destructive actions."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from infra_agent.types.permissions import Deny, PermissionResponse, TypedConfirmValue

# ── Legacy modal (kept for existing unit tests) ──────────────────────────────

class TypedConfirmDialog(ModalScreen[PermissionResponse]):
    def __init__(self, phrase: str, reason: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._phrase = phrase
        self._reason = reason
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(id="typed-confirm-dialog"):
            yield Static(f'Type "{self._phrase}" to confirm', classes="title")
            yield Static(self._reason)
            yield Input(placeholder=self._phrase, id="phrase-input")

    def on_mount(self) -> None:
        self.query_one("#phrase-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._answered:
            return
        self._answered = True
        value = event.value
        if value == self._phrase:
            self.dismiss(TypedConfirmValue(value=value))
        else:
            self.dismiss(Deny())


# ── Inline y/n confirm mounted above the prompt ───────────────────────────────

class InlineConfirmAnswered(Message):
    """Posted when the user answers the inline confirm prompt."""

    def __init__(self, response: PermissionResponse) -> None:
        super().__init__()
        self.response = response


class InlineConfirmDialog(Static):
    """Inline y/n confirmation banner for destructive actions.

    Shows the reason for the confirmation and waits for y (confirm) or n (deny).
    No phrase-typing required — just a single keypress.
    """

    DEFAULT_CSS = """
    InlineConfirmDialog {
        height: auto;
        max-height: 8;
        overflow-y: auto;
        border-top: solid $error;
        padding: 0 1;
        background: $surface;
    }
    """

    can_focus = True

    def __init__(self, phrase: str, reason: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._phrase = phrase
        self._reason = reason
        self._answered = False
        self._update_content()

    def _update_content(self) -> None:
        content = Text()
        content.append("⚠ Confirmation required\n", style="bold red")
        content.append(f"  {self._reason}\n", style="dim")
        content.append("\n")
        content.append("  [y] confirm  ", style="red bold")
        content.append("[n] cancel", style="green")
        self.update(content)

    def on_mount(self) -> None:
        self.focus()

    def answer(self, response: PermissionResponse) -> None:
        if self._answered:
            return
        self._answered = True
        self.post_message(InlineConfirmAnswered(response))

    def on_key(self, event: Key) -> None:
        if self._answered:
            return
        key = event.key.lower()
        if key == "y":
            self.answer(TypedConfirmValue(value=self._phrase))
            event.stop()
        elif key == "n":
            self.answer(Deny())
            event.stop()

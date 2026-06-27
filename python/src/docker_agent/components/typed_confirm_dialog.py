"""Typed phrase confirmation modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from docker_agent.types.permissions import Deny, PermissionResponse, TypedConfirmValue


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
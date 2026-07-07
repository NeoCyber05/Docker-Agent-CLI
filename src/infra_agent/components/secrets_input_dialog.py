"""Secrets input modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from infra_agent.types.permissions import Deny, PermissionResponse, SecretsInputValues


class SecretsInputDialog(ModalScreen[PermissionResponse]):
    def __init__(self, service: str, keys: list[str], reason: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service = service
        self._keys = keys
        self._reason = reason
        self._index = 0
        self._values: dict[str, str] = {}
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(id="secrets-input-dialog"):
            yield Static(f"Service {self._service} needs required env values", classes="title")
            yield Static(self._reason, classes="dim")
            yield Static("", id="key-label")
            yield Input(password=True, id="secret-input")
            yield Static("", id="progress-hint", classes="dim")

    def on_mount(self) -> None:
        self._refresh_labels()
        self.query_one("#secret-input", Input).focus()

    def _current_key(self) -> str:
        return self._keys[self._index]

    def _refresh_labels(self) -> None:
        key = self._current_key()
        masked = "*" * len(self.query_one("#secret-input", Input).value)
        self.query_one("#key-label", Static).update(f"{key}: {masked}")
        self.query_one("#progress-hint", Static).update(
            f"{self._index + 1}/{len(self._keys)} — Enter to submit, Esc to cancel"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "secret-input":
            self._refresh_labels()

    def on_key(self, event: Key) -> None:
        if event.key == "escape" and not self._answered:
            self._answered = True
            self.dismiss(Deny())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "secret-input" or self._answered:
            return
        key = self._current_key()
        self._values[key] = event.value
        event.input.value = ""
        if self._index + 1 >= len(self._keys):
            self._answered = True
            self.dismiss(SecretsInputValues(values=dict(self._values)))
        else:
            self._index += 1
            self._refresh_labels()
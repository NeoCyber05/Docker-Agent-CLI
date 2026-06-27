"""API key input modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from docker_agent.vault.api_key_store import ApiKeyProviderName


class ApiKeyInputDialog(ModalScreen[str | None]):
    def __init__(
        self,
        provider: ApiKeyProviderName,
        env_var_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._provider = provider
        self._env_var_name = env_var_name
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(id="api-key-dialog"):
            yield Static(f"Save API key for {self._provider}", classes="title")
            yield Static("Stored persistently. The value is never printed back.", classes="dim")
            yield Static(self._env_var_name, id="env-label")
            yield Input(password=True, id="api-key-input")
            yield Static("", id="error-label", classes="error")
            yield Static("Enter to save, Esc to cancel", classes="dim")

    def on_mount(self) -> None:
        self.query_one("#api-key-input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape" and not self._answered:
            self._answered = True
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "api-key-input" or self._answered:
            return
        value = event.value.strip()
        if not value:
            self.query_one("#error-label", Static).update("API key cannot be empty")
            return
        self._answered = True
        self.dismiss(value)
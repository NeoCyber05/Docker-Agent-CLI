"""Ollama setup modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static


@dataclass
class OllamaSetupResult:
    action: str
    host: str


class OllamaSetupDialog(ModalScreen[OllamaSetupResult | None]):
    def __init__(self, host: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._default_host = host
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(id="ollama-setup-dialog"):
            yield Static("Connect Ollama", classes="title")
            yield Static(f"Could not reach {self._default_host}.", id="host-message")
            yield Static("Run: ollama serve")
            yield Static("Or set OLLAMA_HOST")
            yield Input(value=self._default_host, id="host-input")
            yield Static("[Enter] retry [Esc] cancel", classes="dim")

    def on_mount(self) -> None:
        self.query_one("#host-input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape" and not self._answered:
            self._answered = True
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "host-input" or self._answered:
            return
        self._answered = True
        self.dismiss(
            OllamaSetupResult(action="retry", host=event.value.strip() or self._default_host)
        )
"""Ollama setup inline panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Input, Static


@dataclass
class OllamaSetupResult:
    action: str
    host: str


class OllamaSetupClosed(Message):
    """Posted when the inline Ollama setup panel is dismissed."""

    def __init__(self, result: OllamaSetupResult | None) -> None:
        super().__init__()
        self.result = result


class OllamaSetupDialog(Vertical):
    """Inline Ollama setup rendered inside the REPL."""

    can_focus = True

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    OllamaSetupDialog {
        height: auto;
        max-height: 12;
        border: round cyan;
        padding: 0 1;
        margin: 1 0;
    }

    OllamaSetupDialog .title {
        text-style: bold;
    }

    OllamaSetupDialog .dim {
        color: $text-muted;
    }
    """

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
        self.call_after_refresh(lambda: self.query_one("#host-input", Input).focus())

    def _close(self, result: OllamaSetupResult | None) -> None:
        if self._answered:
            return
        self._answered = True
        self.post_message(OllamaSetupClosed(result))

    def action_cancel(self) -> None:
        self._close(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self._close(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "host-input" or self._answered:
            return
        self._close(
            OllamaSetupResult(
                action="retry",
                host=event.value.strip() or self._default_host,
            )
        )

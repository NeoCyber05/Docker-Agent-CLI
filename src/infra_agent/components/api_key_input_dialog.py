"""API key input inline panel."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Input, Static

from infra_agent.vault.api_key_store import ApiKeyProviderName


class ApiKeyInputClosed(Message):
    """Posted when the inline API key input is dismissed."""

    def __init__(self, result: str | None) -> None:
        super().__init__()
        self.result = result


class ApiKeyInputDialog(Vertical):
    """Inline API key input rendered inside the REPL."""

    can_focus = True

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ApiKeyInputDialog {
        height: auto;
        max-height: 10;
        border: round cyan;
        padding: 0 1;
        margin: 1 0;
    }

    ApiKeyInputDialog .title {
        text-style: bold;
    }

    ApiKeyInputDialog .dim {
        color: $text-muted;
    }

    ApiKeyInputDialog .error {
        color: $error;
    }
    """

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
        self.call_after_refresh(lambda: self.query_one("#api-key-input", Input).focus())

    def _close(self, result: str | None) -> None:
        if self._answered:
            return
        self._answered = True
        self.post_message(ApiKeyInputClosed(result))

    def action_cancel(self) -> None:
        self._close(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self._close(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "api-key-input" or self._answered:
            return
        value = event.value.strip()
        if not value:
            self.query_one("#error-label", Static).update("API key cannot be empty")
            return
        self._close(value)

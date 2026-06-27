"""Provider connect modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from src.config import PROVIDER_NAMES, ProviderName
from src.services.provider_status import ProviderStatus
from src.vault.api_key_store import API_KEY_PROVIDERS, ApiKeyStatus

PROVIDER_CONNECT_META: dict[ProviderName, dict[str, str]] = {
    "gemini": {"title": "Gemini", "description": "(API key)", "category": "Popular"},
    "openai": {"title": "OpenAI", "description": "(API key)", "category": "Popular"},
    "openrouter": {"title": "OpenRouter", "description": "(API key)", "category": "Popular"},
    "ollama": {"title": "Ollama", "description": "(local)", "category": "Providers"},
}

CATEGORY_ORDER = ("Popular", "Providers")


@dataclass
class ProviderConnectOption:
    provider: ProviderName
    title: str
    description: str
    category: str
    connected: bool
    key_source: str | None = None


def build_provider_connect_options(
    statuses: list[ProviderStatus],
    api_key_statuses: list[ApiKeyStatus] | None = None,
) -> list[ProviderConnectOption]:
    status_by_provider = {status.provider: status for status in statuses}
    key_by_provider = {status.provider: status for status in (api_key_statuses or [])}
    options: list[ProviderConnectOption] = []
    for provider in PROVIDER_NAMES:
        meta = PROVIDER_CONNECT_META[provider]
        status = status_by_provider.get(provider)
        key_status = key_by_provider.get(provider) if provider in API_KEY_PROVIDERS else None
        key_source = None
        if key_status and key_status.state == "set" and key_status.source:
            key_source = key_status.source
        options.append(
            ProviderConnectOption(
                provider=provider,
                title=meta["title"],
                description=meta["description"],
                category=meta["category"],
                connected=status.connected if status else False,
                key_source=key_source,
            )
        )
    return options


class ProviderConnectDialog(ModalScreen[ProviderName | None]):
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        statuses: list[ProviderStatus],
        api_key_statuses: list[ApiKeyStatus] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._options = build_provider_connect_options(statuses, api_key_statuses)
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-connect-dialog"):
            yield Static("Connect a provider", classes="title")
            yield Static("", id="provider-list")
            yield Static("[↑/↓] navigate [Enter] select [Esc] cancel", classes="hint")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        lines: list[str] = []
        for category in CATEGORY_ORDER:
            in_category = [opt for opt in self._options if opt.category == category]
            if not in_category:
                continue
            lines.append(category)
            for option in in_category:
                selectable_index = self._options.index(option)
                selected = selectable_index == self._index
                prefix = "❯ " if selected else "  "
                check = "✓ " if option.connected else "  "
                key_info = f" · {option.key_source}" if option.key_source else ""
                lines.append(f"{prefix}{check}{option.title} {option.description}{key_info}")
        self.query_one("#provider-list", Static).update("\n".join(lines))

    def action_cursor_up(self) -> None:
        if self._options:
            self._index = (self._index - 1) % len(self._options)
            self._refresh_list()

    def action_cursor_down(self) -> None:
        if self._options:
            self._index = (self._index + 1) % len(self._options)
            self._refresh_list()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter" and self._options:
            self.dismiss(self._options[self._index].provider)
"""Model picker modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from src.config import ProviderName
from src.services.model_catalog import CatalogRow, filter_rows, provider_label

PAGE_SIZE = 10


@dataclass
class ModelChoice:
    provider: ProviderName
    model: str


def _selectable_rows(rows: list[CatalogRow]) -> list[CatalogRow]:
    return [row for row in rows if row.kind in {"model", "connect"}]


class ModelPickerDialog(ModalScreen[ModelChoice | str | None]):
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        rows: list[CatalogRow],
        current: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._rows = rows
        self._current = current
        self._query = ""
        self._index = 0
        if current:
            selectable = _selectable_rows(rows)
            for idx, row in enumerate(selectable):
                if (
                    row.kind == "model"
                    and row.provider == current.get("provider")
                    and row.model == current.get("model")
                ):
                    self._index = idx
                    break

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker-dialog"):
            yield Static("Select model", classes="title")
            yield Static("[type to filter]", id="query-label", classes="dim")
            yield Static("", id="model-list")
            yield Static(
                "[↑/↓] navigate [type] filter [Enter] select [Tab] Connect provider [Esc] cancel",
                classes="hint",
            )

    def on_mount(self) -> None:
        self._refresh_list()

    def _filtered(self) -> list[CatalogRow]:
        return filter_rows(self._rows, self._query)

    def _selectable(self) -> list[CatalogRow]:
        return _selectable_rows(self._filtered())

    def _refresh_list(self) -> None:
        filtered = self._filtered()
        selectable = self._selectable()
        if selectable:
            self._index = min(self._index, len(selectable) - 1)
        else:
            self._index = 0

        selected_row = selectable[self._index] if selectable else None
        selected_display_index = filtered.index(selected_row) if selected_row in filtered else 0
        start = min(
            max(0, selected_display_index - PAGE_SIZE // 2),
            max(0, len(filtered) - PAGE_SIZE),
        )
        visible = filtered[start : start + PAGE_SIZE]

        lines: list[str] = []
        if start > 0:
            lines.append(" ↑ more…")
        for row in visible:
            selected = row is selected_row
            prefix = "❯ " if selected else "  "
            if row.kind == "header":
                check = " ✓" if row.connected else ""
                lines.append(f"{provider_label(row.provider)}{check}")
            elif row.kind == "connect":
                lines.append(f"{prefix}Not connected")
            else:
                current = (
                    self._current
                    and row.provider == self._current.get("provider")
                    and row.model == self._current.get("model")
                )
                suffix = " (current)" if current else ""
                lines.append(f"{prefix}{row.model}{suffix}")
        if start + PAGE_SIZE < len(filtered):
            lines.append(" ↓ more…")

        self.query_one("#query-label", Static).update(
            self._query if self._query else "[type to filter]"
        )
        self.query_one("#model-list", Static).update("\n".join(lines))

    def action_cursor_up(self) -> None:
        selectable = self._selectable()
        if selectable:
            self._index = (self._index - 1) % len(selectable)
            self._refresh_list()

    def action_cursor_down(self) -> None:
        selectable = self._selectable()
        if selectable:
            self._index = (self._index + 1) % len(selectable)
            self._refresh_list()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            self.dismiss("connect")
            return
        if event.key == "enter":
            selectable = self._selectable()
            if not selectable:
                return
            choice = selectable[self._index]
            if choice.kind == "model":
                self.dismiss(ModelChoice(provider=choice.provider, model=choice.model))
            elif choice.kind == "connect":
                self.dismiss("connect")
            return
        if event.character and len(event.character) == 1 and event.character.isprintable():
            if event.key == "backspace":
                self._query = self._query[:-1]
            else:
                self._query += event.character
            self._index = 0
            self._refresh_list()
        elif event.key == "backspace":
            self._query = self._query[:-1]
            self._index = 0
            self._refresh_list()
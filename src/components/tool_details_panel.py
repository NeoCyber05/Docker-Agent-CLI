"""Tool details side panel."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from src.ui.activity import ToolActivity


def render_tool_details(activity: ToolActivity | None) -> Text:
    if activity is None:
        return Text("No tool selected.", style="dim")

    content = Text()
    content.append(f"{activity.title}\n", style="bold")
    content.append(f"{activity.summary}\n", style="dim")
    content.append(f"Status: {activity.status}\n", style="dim")
    if activity.progress_msgs:
        content.append("\nProgress\n", style="underline")
        for msg in activity.progress_msgs:
            content.append(f"{msg}\n", style="dim")
    if activity.detail_lines:
        content.append("\nDetails\n", style="underline")
        for line in activity.detail_lines:
            content.append(f"{line}\n")
    return content


class ToolDetailsPanel(Static):
    def __init__(self, activity: ToolActivity | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.activity = activity
        self.update(render_tool_details(activity))


class ToolDetailsModal(ModalScreen[None]):
    def __init__(self, activity: ToolActivity | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._activity = activity

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-details-modal"):
            yield ToolDetailsPanel(self._activity)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
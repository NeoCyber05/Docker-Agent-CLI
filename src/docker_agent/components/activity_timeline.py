"""Activity feed timeline widget."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.widgets import Static

from docker_agent.ui.activity import (
    ActivityItem,
    RollbackActivity,
    TextActivity,
    ToolActivity,
    UsageActivity,
)


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{int(ms)}ms"
    return f"{ms / 1000:.1f}s"


def _status_symbol(status: str) -> str:
    return {"running": "●", "completed": "✓", "failed": "!", "cancelled": "×"}.get(status, "●")


def _render_tool(activity: ToolActivity, *, is_active: bool = False) -> Text:
    content = Text()
    duration = ""
    if activity.end_time is not None:
        duration = _format_duration((activity.end_time - activity.start_time) * 1000)
    elif is_active:
        duration = _format_duration((time.time() - activity.start_time) * 1000)

    symbol_style = "yellow" if is_active else ""
    content.append(_status_symbol(activity.status), style=symbol_style)
    content.append(" ")
    content.append(activity.title, style="bold")
    content.append(f" ({activity.summary})", style="dim")
    content.append(f" [{activity.status}]", style="dim")
    if duration:
        content.append(f" {duration}", style="dim")
    content.append("\n")

    for msg in activity.progress_msgs[-3:]:
        content.append(f"  {msg}\n", style="dim")
    return content


def _render_text(item: TextActivity) -> Text:
    content = Text()
    if item.role == "user":
        content.append("▶ ", style="bold green")
        content.append(item.text, style="green")
    elif item.role == "error":
        content.append(f"error: {item.text}", style="red")
    else:
        content.append("Agent\n", style="bold magenta")
        content.append(item.text)
    content.append("\n")
    return content


def _render_usage(item: UsageActivity) -> Text:
    return Text(
        f"usage: {item.input_tokens} in / {item.output_tokens} out\n",
        style="dim",
    )


def _render_rollback(item: RollbackActivity) -> Text:
    style = "red" if item.ok is False else "yellow"
    suffix = ""
    if item.ok is not None:
        suffix = f" — {'ok' if item.ok else 'FAILED'}"
    return Text(f"rollback {item.phase} for {item.stack_name}{suffix}\n", style=style)


def render_activity_timeline(
    items: list[ActivityItem],
    active_tool_activity_id: str | None = None,
) -> Text:
    active_item = next(
        (item for item in items if item.type == "tool" and item.id == active_tool_activity_id),
        None,
    )
    last_item = items[-1] if items else None
    active_text = (
        last_item
        if last_item and last_item.type == "text" and last_item.role == "assistant"
        else None
    )
    committed = [
        item
        for item in items
        if not (item.type == "tool" and item.id == active_tool_activity_id)
        and (active_text is None or item.id != active_text.id)
        and item.type != "usage"
    ]

    content = Text()
    for item in committed:
        if item.type == "tool":
            content.append_text(_render_tool(item))
        elif item.type == "text":
            content.append_text(_render_text(item))
        elif item.type == "rollback":
            content.append_text(_render_rollback(item))

    if active_item and active_item.type == "tool":
        content.append_text(_render_tool(active_item, is_active=True))
    if active_text and active_text.type == "text":
        content.append_text(_render_text(active_text))
    return content


class ActivityTimeline(Static):
    """Widget rendering a list of ActivityItem rows."""

    def __init__(
        self,
        items: list[ActivityItem] | None = None,
        active_tool_activity_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.items = items or []
        self.active_tool_activity_id = active_tool_activity_id
        self.refresh_timeline()

    def refresh_timeline(self) -> None:
        self.update(render_activity_timeline(self.items, self.active_tool_activity_id))
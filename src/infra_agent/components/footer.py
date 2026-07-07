"""Session status footer."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from infra_agent.config import resolve_display_model


def build_footer_content(
    *,
    usage: dict[str, int] | None = None,
    session_id: str | None = None,
    active_tool: str | None = None,
    queue_count: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Text:
    usage = usage or {"input_tokens": 0, "output_tokens": 0}
    parts: list[tuple[str, str]] = []

    if provider:
        model_label = resolve_display_model(provider, model) or "unknown"
        parts.append((f"{model_label} ({provider})", "bold cyan"))

    if session_id:
        parts.append((f"session: {session_id}", "dim"))
    parts.append(
        (
            f"tokens in/out: {usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}",
            "dim",
        )
    )
    if active_tool:
        parts.append((f"● {active_tool} (Ctrl+O details)", "yellow"))
    if queue_count is not None and queue_count > 0:
        parts.append((f"queue: {queue_count}", "dim"))

    content = Text()
    for index, (text, style) in enumerate(parts):
        if index:
            content.append("  ", style="dim")
        content.append(text, style=style)
    return content


class StatusFooter(Static):
    """Footer-like status bar for session, tokens, tool, and queue."""

    def __init__(
        self,
        *,
        usage: dict[str, int] | None = None,
        session_id: str | None = None,
        active_tool: str | None = None,
        queue_count: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.update(
            build_footer_content(
                usage=usage,
                session_id=session_id,
                active_tool=active_tool,
                queue_count=queue_count,
                provider=provider,
                model=model,
            )
        )


Footer = StatusFooter
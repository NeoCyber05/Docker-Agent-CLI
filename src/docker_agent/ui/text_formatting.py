"""Inline text formatting helpers for Rich/Textual rendering."""

from __future__ import annotations

import re

from rich.text import Text

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")


def render_inline_markdown(
    text: str,
    *,
    base_style: str = "",
    emphasis_style: str = "bold cyan",
    italic_style: str = "italic",
    code_style: str = "cyan",
) -> Text:
    """Render basic inline markdown markers as styled Rich text.

    Supports ``**bold**``, ``*italic*``, and ``inline code``.
    """
    if not text:
        return Text("", style=base_style)

    segments: list[tuple[str, str]] = [(text, base_style)]
    for pattern, style in (
        (_BOLD_PATTERN, emphasis_style),
        (_ITALIC_PATTERN, italic_style),
        (_INLINE_CODE_PATTERN, code_style),
    ):
        updated: list[tuple[str, str]] = []
        for segment_text, segment_style in segments:
            if segment_style != base_style:
                updated.append((segment_text, segment_style))
                continue
            last_end = 0
            matched = False
            for match in pattern.finditer(segment_text):
                matched = True
                if match.start() > last_end:
                    updated.append((segment_text[last_end : match.start()], base_style))
                updated.append((match.group(1), style))
                last_end = match.end()
            if not matched:
                updated.append((segment_text, segment_style))
            elif last_end < len(segment_text):
                updated.append((segment_text[last_end:], base_style))
        segments = updated

    result = Text()
    for segment_text, segment_style in segments:
        if segment_text:
            result.append(segment_text, style=segment_style)
    return result


__all__ = ["render_inline_markdown"]

"""Highlight slash commands in the prompt input."""

from __future__ import annotations

import re

from rich.highlighter import Highlighter
from rich.text import Text

from docker_agent.slash.router import HANDLER_KEYS

_SLASH_COMMAND_STYLE = "bold cyan"


def slash_command_range(line: str) -> tuple[int, int] | None:
    """Return start/end offsets of the slash command token on a single line."""
    stripped = line.lstrip()
    if not stripped.startswith("/"):
        return None

    offset = len(line) - len(stripped)
    lower = stripped.lower()
    for key in sorted(HANDLER_KEYS, key=len, reverse=True):
        key_lower = key.lower()
        if not lower.startswith(key_lower):
            continue
        after = lower[len(key_lower) :]
        if after and after[0] not in " \t":
            continue
        return offset, offset + len(key)

    match = re.match(r"/\S+", stripped)
    if match:
        return offset, offset + match.end()
    return None


class SlashCommandHighlighter(Highlighter):
    """Colorize leading slash commands in prompt text."""

    def highlight(self, text: Text) -> None:
        plain = text.plain
        if not plain:
            return

        line_start = 0
        for line in plain.split("\n"):
            span = slash_command_range(line)
            if span:
                start, end = span
                text.stylize(_SLASH_COMMAND_STYLE, line_start + start, line_start + end)
            line_start += len(line) + 1


__all__ = ["SlashCommandHighlighter", "slash_command_range"]

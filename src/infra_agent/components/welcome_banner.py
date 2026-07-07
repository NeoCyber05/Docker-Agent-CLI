"""Welcome banner with whale ASCII art."""

from __future__ import annotations

import getpass
import os
import shutil
from typing import Any, Literal

from rich.columns import Columns
from rich.text import Text
from textual.widgets import Static

WHALE = [
    "           ##         .",
    "     ## ## ##        ==",
    "  ## ## ## ##       ===",
    ' /"""""""""""""""\\___/ ===',
    "{                  /  ===-",
    " \\______ o         __/",
    "  \\    \\         __/",
    "   \\____\\_______/",
]

COMPACT_WELCOME_MAX_ROWS = 16
COMPACT_WELCOME_MIN_COLUMNS = 84
 
TIPS = [
    ("/help", "Show all commands & shortcuts"),
    ("/model", "Browse or set the active model"),
    ("/connect", "Connect gemini, openai, or ollama"),
    ("/stacks", "List managed stacks"),
    ("Ctrl+O", "Open tool details panel"),
    ("/exit", "Exit the agent"),
]

SegType = Literal["container", "water", "eye", "outline"]


def resolve_terminal_size(
    columns: int | None = None,
    rows: int | None = None,
) -> tuple[int, int]:
    if columns is not None and rows is not None:
        return columns, rows
    try:
        size = shutil.get_terminal_size(fallback=(80, 24))
    except (OSError, ValueError):
        size = os.terminal_size(columns=80, lines=24)
    return (
        columns if columns is not None else size.columns,
        rows if rows is not None else size.lines,
    )


def should_show_compact_banner(columns: int, rows: int) -> bool:
    effective_columns = max(1, columns - 1)
    return (
        rows <= COMPACT_WELCOME_MAX_ROWS
        or effective_columns < COMPACT_WELCOME_MIN_COLUMNS
    )


def _char_type(ch: str) -> SegType:
    if ch == "#":
        return "container"
    if ch in {"o", "●"}:
        return "eye"
    if ch in {"=", ".", "~"}:
        return "water"
    return "outline"


def _seg_style(seg_type: SegType) -> str:
    if seg_type == "container":
        return "blue"
    if seg_type == "eye":
        return "green"
    return "cyan"


def _colorize_line(line: str) -> Text:
    result = Text()
    buf = ""
    current: SegType = "outline"
    for ch in line:
        seg = _char_type(ch)
        if seg != current:
            if buf:
                result.append(buf, style=_seg_style(current))
            buf = ch
            current = seg
        else:
            buf += ch
    if buf:
        result.append(buf, style=_seg_style(current))
    return result


def build_whale_column(username: str | None = None) -> Text:
    user = username or getpass.getuser()
    content = Text()
    content.append("Welcome back, ", style="bold")
    content.append(f"{user}", style="bold cyan")
    content.append("!\n\n")
    for line in WHALE:
        content.append_text(_colorize_line(line))
        content.append("\n")
    content.append("\ninfra-agent CLI\n", style="bold cyan")
    content.append("Your AI teammate for infrastructure workflows", style="dim")
    return content


def build_tips_column() -> Text:
    content = Text()
    content.append("Tips for getting started\n\n", style="bold cyan")
    for cmd, desc in TIPS:
        content.append("> ", style="cyan")
        content.append(f"{cmd:<20}", style="cyan")
        content.append(f"{desc}\n")
    return content


def build_welcome_content(
    version: str,
    *,
    username: str | None = None,
    compact: bool = False,
) -> Text | Columns:
    if compact:
        content = Text()
        content.append("infra-agent ", style="bold cyan")
        content.append(f"v{version}", style="cyan")
        return content

    return Columns(
        [build_whale_column(username), build_tips_column()],
        equal=False,
        expand=True,
    )


class WelcomeBanner(Static):
    """Two-column welcome banner: whale art on the left, tips on the right."""

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        border: round cyan;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        version: str,
        *,
        username: str | None = None,
        provider: str = "",
        model: str | None = None,
        compact: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.update(
            build_welcome_content(version, username=username, compact=compact)
        )
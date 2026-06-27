"""Welcome banner with whale ASCII art."""

from __future__ import annotations

import getpass
from typing import Any, Literal

from rich.text import Text
from textual.widgets import Static

WHALE = [
    "          ##         .",
    "    ## ## ##        ==",
    " ## ## ## ##       ===",
    '/"""""""""""""""\\___/ ===',
    "{                   /  ===-",
    "\\______ o         __/",
    " \\    \\         __/",
    "  \\____\\_______/",
]

TIPS = [
    ("/help", "Show all commands & shortcuts"),
    ("/model", "Browse or set the active model"),
    ("/connect", "Connect gemini, openai, or ollama"),
    ("/stacks", "List managed stacks"),
    ("Ctrl+O", "Open tool details panel"),
    ("/exit", "Exit the agent"),
]

SegType = Literal["container", "water", "eye", "outline"]


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


def build_welcome_content(
    version: str,
    *,
    username: str | None = None,
    compact: bool = False,
) -> Text:
    user = username or getpass.getuser()
    if compact:
        content = Text()
        content.append("docker-agent ", style="bold cyan")
        content.append(f"v{version}", style="cyan")
        return content

    content = Text()
    content.append(f"Welcome back, {user}!\n", style="bold")
    for line in WHALE:
        content.append_text(_colorize_line(line))
        content.append("\n")
    content.append("\nDocker Agent CLI\n", style="bold cyan")
    content.append("Your AI teammate for containerized workflows\n", style="dim")
    content.append("\nTips for getting started\n", style="bold cyan")
    for cmd, desc in TIPS:
        content.append("> ", style="cyan")
        content.append(f"{cmd:<20}", style="cyan")
        content.append(f"{desc}\n")
    return content


class WelcomeBanner(Static):
    """Static widget rendering whale ASCII art and tips."""

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
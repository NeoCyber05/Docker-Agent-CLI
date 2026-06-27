from __future__ import annotations

from docker_agent.components.welcome_banner import (
    build_welcome_content,
    should_show_compact_banner,
)


def test_should_show_compact_banner_uses_full_terminal_not_inline_region() -> None:
    assert should_show_compact_banner(120, 8) is True
    assert should_show_compact_banner(120, 30) is False
    assert should_show_compact_banner(80, 30) is True
    assert should_show_compact_banner(100, 30) is False


def test_build_welcome_content_shows_whale_when_not_compact() -> None:
    from io import StringIO

    from rich.console import Console

    buffer = StringIO()
    Console(file=buffer, width=100).print(build_welcome_content("0.1.0", compact=False))
    text = buffer.getvalue()
    assert "##" in text
    assert "Tips for getting started" in text
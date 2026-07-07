from __future__ import annotations

from rich.text import Text

from infra_agent.components.slash_highlighter import (
    SlashCommandHighlighter,
    slash_command_range,
)


def test_slash_command_range_model() -> None:
    assert slash_command_range("/model") == (0, 6)
    assert slash_command_range("/model openai/gpt-4.1-mini") == (0, 6)


def test_slash_command_range_multi_word_command() -> None:
    assert slash_command_range("/destroy all") == (0, 12)


def test_slash_command_range_partial_typing() -> None:
    assert slash_command_range("/mod") == (0, 4)


def test_slash_command_range_ignores_normal_text() -> None:
    assert slash_command_range("deploy nginx") is None
    assert slash_command_range("try /model") is None


def test_slash_command_highlighter_applies_style() -> None:
    highlighter = SlashCommandHighlighter()
    highlighted = highlighter(Text("/model hello"))
    assert "bold cyan" in highlighted._spans[0].style


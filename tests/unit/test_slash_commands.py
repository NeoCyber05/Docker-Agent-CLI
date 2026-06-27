"""Parity tests for slash command autocomplete."""

from __future__ import annotations

from src.slash_commands import SLASH_COMMANDS, get_slash_command_suggestions
from src.slash_router import SLASH_COMMAND_DEFS


def test_slash_commands_matches_defs() -> None:
    assert SLASH_COMMANDS == SLASH_COMMAND_DEFS


def test_get_slash_command_suggestions_filters_by_prefix() -> None:
    suggestions = get_slash_command_suggestions("/hel")
    assert any(command.usage == "/help" for command in suggestions)
    assert all(
        command.usage.lower().startswith("/hel")
        or command.insert_text.rstrip().lower().startswith("/hel")
        for command in suggestions
    )


def test_get_slash_command_suggestions_returns_empty_for_non_slash() -> None:
    assert get_slash_command_suggestions("help") == []


def test_get_slash_command_suggestions_returns_empty_for_trailing_space() -> None:
    assert get_slash_command_suggestions("/help ") == []


def test_get_slash_command_suggestions_returns_empty_for_multiline() -> None:
    assert get_slash_command_suggestions("/help\nmore") == []
"""Parity tests for welcome banner pre-render and inline TUI launch."""

from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

from src.cli import (
    ParsedArgs,
    _run_chat_session,
    render_welcome_banner_for_terminal,
)


def test_render_welcome_banner_for_terminal_returns_text() -> None:
    output = render_welcome_banner_for_terminal("gemini", columns=100, rows=30)
    assert "docker-agent" in output.lower() or "Welcome" in output
    assert "\u001b[?1049h" not in output
    assert "\u001b[2J" not in output


def test_render_chat_session_inline_without_alternate_screen() -> None:
    stdout = StringIO()
    with (
        patch("src.cli.sys.stdout", new=stdout),
        patch("src.cli._create_deps") as mock_create,
        patch("src.cli._resolve_resume") as mock_resolve,
        patch("src.cli.QueryEngine") as mock_engine_cls,
    ):
        mock_engine = MagicMock()
        mock_engine.session_id = "sess-test"
        mock_engine_cls.return_value = mock_engine
        mock_create.return_value = {
            "cwd": "/tmp",
            "state_store": MagicMock(),
            "session_store": MagicMock(),
            "compose_runner": MagicMock(),
            "docker_engine": MagicMock(),
            "provider": MagicMock(),
            "provider_name": "gemini",
            "api_key_store": MagicMock(),
        }
        mock_resolve.return_value = None
        fake_app = MagicMock()
        _run_chat_session(ParsedArgs(), app_factory=lambda **_kwargs: fake_app)
        fake_app.run.assert_called_once_with(inline=True)

    output = stdout.getvalue()
    assert "\u001b[?1049h" not in output
    assert "\u001b[?1049l" not in output
    assert "\u001b[2J" not in output


def test_render_chat_session_writes_banner_to_stdout() -> None:
    stdout = StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout
    try:
        with (
            patch("src.cli._create_deps") as mock_create,
            patch("src.cli._resolve_resume") as mock_resolve,
            patch("src.cli.QueryEngine") as mock_engine_cls,
        ):
            mock_engine = MagicMock()
            mock_engine.session_id = "sess-test"
            mock_engine_cls.return_value = mock_engine
            mock_create.return_value = {
                "cwd": "/tmp",
                "state_store": MagicMock(),
                "session_store": MagicMock(),
                "compose_runner": MagicMock(),
                "docker_engine": MagicMock(),
                "provider": MagicMock(),
                "provider_name": "gemini",
                "api_key_store": MagicMock(),
            }
            mock_resolve.return_value = None
            fake_app = MagicMock()
            _run_chat_session(ParsedArgs(), app_factory=lambda **_kwargs: fake_app)
    finally:
        sys.stdout = old_stdout

    assert len(stdout.getvalue()) > 0
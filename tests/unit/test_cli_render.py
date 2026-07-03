"""Parity tests for welcome banner pre-render and inline TUI launch."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from docker_agent.cli import (
    ParsedArgs,
    _run_chat_session,
    render_welcome_banner_for_terminal,
)


def test_render_welcome_banner_for_terminal_returns_text() -> None:
    output = render_welcome_banner_for_terminal("gemini", columns=100, rows=30)
    assert "docker-agent" in output.lower() or "Welcome" in output
    assert "\u001b[?1049h" not in output
    assert "\u001b[2J" not in output


def test_render_welcome_banner_shows_whale_on_wide_terminal() -> None:
    output = render_welcome_banner_for_terminal("gemini", columns=100, rows=30)
    assert "##" in output
    assert "Tips for getting started" in output


def test_render_welcome_banner_uses_compact_only_on_small_terminals() -> None:
    output = render_welcome_banner_for_terminal("gemini", columns=80, rows=12)
    assert "##" not in output
    assert "docker-agent" in output.lower()


def test_render_chat_session_inline_without_alternate_screen() -> None:
    stdout = StringIO()
    with (
        patch("docker_agent.cli.sys.stdout", new=stdout),
        patch("docker_agent.cli._create_deps") as mock_create,
        patch("docker_agent.cli._resolve_resume") as mock_resolve,
        patch("docker_agent.cli.QueryEngine") as mock_engine_cls,
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


def test_render_chat_session_shows_banner_in_repl() -> None:
    captured: dict[str, object] = {}

    def capture_factory(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    with (
        patch("docker_agent.cli._create_deps") as mock_create,
        patch("docker_agent.cli._resolve_resume") as mock_resolve,
        patch("docker_agent.cli.QueryEngine") as mock_engine_cls,
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
        _run_chat_session(ParsedArgs(), app_factory=capture_factory)

    assert captured.get("show_banner") is True
"""Parity tests for CLI argument parsing."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from docker_agent.cli import _RESUME_LATEST, _normalize_resume_argv, cli

runner = CliRunner()


def invoke_and_capture(argv: list[str]) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_run(args: object) -> None:
        captured["args"] = args

    with (
        patch("docker_agent.cli.run_chat_session", fake_run),
        patch("docker_agent.cli._normalize_resume_argv", side_effect=lambda a: a),
    ):
        result = runner.invoke(cli, argv)
    return {"result": result, "captured": captured}


def test_default_parses_empty_args() -> None:
    data = invoke_and_capture([])
    result = data["result"]
    assert result.exit_code == 0
    args = data["captured"]["args"]
    assert args.provider_flag is None
    assert args.model is None
    assert args.resume is None
    assert args.yes is False


def test_provider_flag_captured() -> None:
    data = invoke_and_capture(["--provider", "ollama"])
    assert data["result"].exit_code == 0
    assert data["captured"]["args"].provider_flag == "ollama"


def test_model_flag_captured() -> None:
    data = invoke_and_capture(["--model", "gpt-4o"])
    assert data["captured"]["args"].model == "gpt-4o"


def test_yes_flag_captured() -> None:
    data = invoke_and_capture(["-y"])
    assert data["captured"]["args"].yes is True


def test_normalize_resume_argv_maps_bare_flag() -> None:
    assert _normalize_resume_argv(["--resume"]) == ["--resume", _RESUME_LATEST]


def test_resume_flag_captured_as_true_if_no_value() -> None:
    data = invoke_and_capture(["--resume", _RESUME_LATEST])
    assert data["captured"]["args"].resume is True


def test_resume_flag_captured_as_string_if_value_provided() -> None:
    data = invoke_and_capture(["--resume", "12345"])
    assert data["captured"]["args"].resume == "12345"
"""Smoke tests for the CLI entrypoint."""

from __future__ import annotations

from typer.testing import CliRunner

from docker_agent.cli import cli

runner = CliRunner()


def test_version_exits_with_code_0_and_prints_version() -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help_lists_core_options() -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output
    assert "--yes" in result.output
    assert "--resume" in result.output
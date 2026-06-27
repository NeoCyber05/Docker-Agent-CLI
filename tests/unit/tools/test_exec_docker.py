"""Parity tests for exec_docker whitelist."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docker_agent.tools.exec_docker import ExecDockerInput


def test_allowed_subcommand_passes_validation() -> None:
    parsed = ExecDockerInput(args=["ps", "--all"])
    assert parsed.args == ["ps", "--all"]


def test_rejected_subcommands_fail_validation() -> None:
    for args in (
        ["rm", "-f", "abc"],
        ["exec", "x", "sh"],
        ["prune"],
        ["kill", "x"],
    ):
        with pytest.raises(ValidationError):
            ExecDockerInput(args=args)
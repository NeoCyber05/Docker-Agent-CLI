"""Tests for exec_docker whitelist and permission logic."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docker_mcp_server.tools.exec_docker import (
    ExecDockerInput,
    _is_allowed_docker_args,
    _needs_permission_for_args,
)


# ---------------------------------------------------------------------------
# Whitelist validation
# ---------------------------------------------------------------------------

class TestWhitelist:
    """_is_allowed_docker_args covers all permitted / blocked cases."""

    @pytest.mark.parametrize("args", [
        # Simple read-only top-level
        ["ps", "--all"],
        ["inspect", "my-container"],
        ["logs", "my-container"],
        ["images"],
        # Network read-only
        ["network", "ls"],
        ["network", "inspect", "my-net"],
        # Network mutating
        ["network", "create", "my-net"],
        ["network", "rm", "my-net"],
        ["network", "remove", "my-net"],
        ["network", "connect", "my-net", "my-container"],
        ["network", "disconnect", "my-net", "my-container"],
        ["network", "prune", "-f"],
        # Volume read-only
        ["volume", "ls"],
        ["volume", "inspect", "my-vol"],
        # Volume mutating
        ["volume", "create", "my-vol"],
        ["volume", "rm", "my-vol"],
        ["volume", "prune", "-f"],
    ])
    def test_allowed(self, args: list[str]) -> None:
        assert _is_allowed_docker_args(args) is True
        parsed = ExecDockerInput(args=args)
        assert parsed.args == args

    @pytest.mark.parametrize("args", [
        # Flat rejected keywords
        ["rm", "-f", "abc"],
        ["exec", "x", "sh"],
        ["kill", "x"],
        ["stop", "x"],
        ["restart", "x"],
        ["system", "prune"],
        # Network with no subcommand
        ["network"],
        # Unknown subcommand
        ["network", "unknown"],
        ["volume", "unknown"],
        # Empty
        [],
    ])
    def test_rejected(self, args: list[str]) -> None:
        assert _is_allowed_docker_args(args) is False

    def test_rejected_raises_validation_error(self) -> None:
        for args in (["rm", "-f", "abc"], ["exec", "x", "sh"], ["kill", "x"]):
            with pytest.raises(ValidationError):
                ExecDockerInput(args=args)


# ---------------------------------------------------------------------------
# Permission logic
# ---------------------------------------------------------------------------

class TestNeedsPermission:
    """_needs_permission_for_args drives the UX gate."""

    @pytest.mark.parametrize("args", [
        # Simple read-only: no permission
        ["ps", "--all"],
        ["inspect", "my-container"],
        ["logs", "my-container"],
        ["images"],
        # Network read-only: no permission
        ["network", "ls"],
        ["network", "inspect", "my-net"],
        # Volume read-only: no permission
        ["volume", "ls"],
        ["volume", "inspect", "my-vol"],
    ])
    def test_no_permission_needed(self, args: list[str]) -> None:
        assert _needs_permission_for_args(args) is False
        parsed = ExecDockerInput(args=args)
        from docker_mcp_server.tools.exec_docker import exec_docker
        assert exec_docker.needs_permission(parsed) is False

    @pytest.mark.parametrize("args", [
        # Network mutating: permission required
        ["network", "create", "my-net"],
        ["network", "rm", "my-net"],
        ["network", "remove", "my-net"],
        ["network", "connect", "my-net", "my-container"],
        ["network", "disconnect", "my-net", "my-container"],
        ["network", "prune", "-f"],
        # Volume mutating: permission required
        ["volume", "create", "my-vol"],
        ["volume", "rm", "my-vol"],
        ["volume", "prune", "-f"],
    ])
    def test_permission_required(self, args: list[str]) -> None:
        assert _needs_permission_for_args(args) is True
        parsed = ExecDockerInput(args=args)
        from docker_mcp_server.tools.exec_docker import exec_docker
        assert exec_docker.needs_permission(parsed) is True

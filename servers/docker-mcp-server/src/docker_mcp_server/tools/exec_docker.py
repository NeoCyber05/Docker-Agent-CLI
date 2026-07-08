"""exec_docker tool.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import BaseModel, Field, field_validator

from docker_mcp_server.services.docker.compose_runner import docker_child_env
from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress

_SIMPLE_READ_ONLY = frozenset({"ps", "inspect", "logs", "images"})

# Subcommands allowed for group commands (network / volume) broken out by risk.
# Read-only: no permission prompt needed.
# Mutating: requires user confirmation (needs_permission returns True).
_GROUP_READ_ONLY = frozenset({"ls", "inspect"})
_GROUP_MUTATING = frozenset({"create", "rm", "remove", "connect", "disconnect", "prune"})
_GROUP_COMMANDS = frozenset({"network", "volume"})

# Top-level commands that are always rejected (even if a subcommand would be ok).
_REJECTED = frozenset({"rm", "kill", "exec", "stop", "restart", "system"})


def _is_group_subcommand_allowed(args: list[str]) -> bool:
    """Return True if args is a permitted group command (network or volume)."""
    if len(args) < 2:
        return False
    head, sub = args[0], args[1]
    if head not in _GROUP_COMMANDS:
        return False
    return sub in _GROUP_READ_ONLY or sub in _GROUP_MUTATING


def _is_group_subcommand_mutating(args: list[str]) -> bool:
    """Return True if the group command modifies Docker state."""
    return len(args) >= 2 and args[0] in _GROUP_COMMANDS and args[1] in _GROUP_MUTATING


def _is_allowed_docker_args(args: list[str]) -> bool:
    if not args:
        return False
    head = args[0]
    if head in _REJECTED:
        return False
    if head in _SIMPLE_READ_ONLY:
        return True
    return _is_group_subcommand_allowed(args)


def _needs_permission_for_args(args: list[str]) -> bool:
    """Return True when the command mutates Docker state and needs a user prompt."""
    if not args:
        return True
    # Simple read-only top-level commands don't need permission.
    if args[0] in _SIMPLE_READ_ONLY:
        return False
    # Group read-only subcommands (network ls, network inspect, volume ls, volume inspect)
    # don't need permission.
    if _is_group_subcommand_allowed(args) and not _is_group_subcommand_mutating(args):
        return False
    # Everything else that passes validation is mutating.
    return True


class ExecDockerInput(BaseModel):
    args: list[str] = Field(min_length=1)

    @field_validator("args")
    @classmethod
    def _validate_whitelist(cls, value: list[str]) -> list[str]:
        if not _is_allowed_docker_args(value):
            raise ValueError("subcommand not in whitelist")
        return value


class ExecDockerResult(BaseModel):
    exit_code: int = Field(alias="exitCode")
    stdout: str
    stderr: str

    model_config = {"populate_by_name": True}


class _ExecDockerTool:
    name = "exec_docker"
    description = (
        "Run a docker subcommand from the allowed whitelist.\n"
        "Read-only (no permission required): ps, inspect, logs, images, "
        "network ls, network inspect, volume ls, volume inspect.\n"
        "Mutating (requires user permission): "
        "network create, network rm, network connect, network disconnect, network prune, "
        "volume create, volume rm, volume prune."
    )
    input_schema = ExecDockerInput
    category = "escape-hatch"

    def needs_permission(self, input: ExecDockerInput) -> bool:  # type: ignore[override]
        args = input.args if isinstance(input, ExecDockerInput) else []
        return _needs_permission_for_args(args)

    async def call(
        self, input: ExecDockerInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg=f"docker {' '.join(input.args)}")

        proc = await asyncio.create_subprocess_exec(
            "docker",
            *input.args,
            cwd=ctx.cwd,
            env=docker_child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        yield ToolDone(
            ExecDockerResult(
                exit_code=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )
        )


exec_docker = _ExecDockerTool()

__all__ = [
    "ExecDockerInput",
    "ExecDockerResult",
    "exec_docker",
    "_is_allowed_docker_args",
    "_needs_permission_for_args",
]

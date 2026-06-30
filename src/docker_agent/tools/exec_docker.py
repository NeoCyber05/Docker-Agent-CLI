"""exec_docker tool.

Parity: ``src/tools/execDocker.ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import BaseModel, Field, field_validator

from docker_agent.tools.base import ToolContext, ToolDone, ToolProgress

_SIMPLE_READ_ONLY = frozenset({"ps", "inspect", "logs", "images"})
_READ_ONLY_GROUPS = frozenset({"network", "volume"})
_REJECTED = frozenset({"rm", "kill", "prune", "exec", "stop", "restart", "system"})


def _is_allowed_docker_args(args: list[str]) -> bool:
    if not args:
        return False
    head = args[0]
    if head in _REJECTED:
        return False
    if head in _SIMPLE_READ_ONLY:
        return True
    return head in _READ_ONLY_GROUPS and len(args) > 1 and args[1] == "ls"


class ExecDockerInput(BaseModel):
    args: list[str] = Field(min_length=1)

    @field_validator("args")
    @classmethod
    def _validate_whitelist(cls, value: list[str]) -> list[str]:
        if not _is_allowed_docker_args(value):
            raise ValueError("subcommand not in read-only whitelist")
        return value


class ExecDockerResult(BaseModel):
    exit_code: int = Field(alias="exitCode")
    stdout: str
    stderr: str

    model_config = {"populate_by_name": True}


class _ExecDockerTool:
    name = "exec_docker"
    description = (
        "Run a read-only docker subcommand (ps, inspect, logs, images, network ls, volume ls)."
    )
    input_schema = ExecDockerInput
    category = "escape-hatch"

    def needs_permission(self, _input: ExecDockerInput) -> bool:
        return True

    async def call(
        self, input: ExecDockerInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg=f"docker {' '.join(input.args)}")

        proc = await asyncio.create_subprocess_exec(
            "docker",
            *input.args,
            cwd=ctx.cwd,
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

__all__ = ["ExecDockerInput", "ExecDockerResult", "exec_docker"]
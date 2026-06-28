"""remove_container tool — stop and remove physical Docker containers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel, Field, field_validator

from docker_agent.tool import ToolContext, ToolDone, ToolProgress

MAX_CONTAINERS_PER_CALL = 8
_BULK_NAME_PATTERN = re.compile(r"[\*\?]|\$\(|docker\s+(container\s+)?prune", re.I)


class RemoveContainerInput(BaseModel):
    containers: list[str] = Field(min_length=1, max_length=MAX_CONTAINERS_PER_CALL)
    force: bool = True
    stop_only: bool = Field(default=False, alias="stopOnly")

    model_config = {"populate_by_name": True}

    @field_validator("containers")
    @classmethod
    def _validate_container_names(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for name in value:
            stripped = name.strip()
            if not stripped:
                raise ValueError("container name must not be empty")
            if _BULK_NAME_PATTERN.search(stripped):
                raise ValueError(
                    f"bulk or wildcard container removal is not allowed: {name!r}"
                )
            normalized.append(stripped)
        return normalized


class RemoveContainerFailure(BaseModel):
    name: str
    exit_code: int = Field(alias="exitCode")
    stderr: str = ""

    model_config = {"populate_by_name": True}


class RemoveContainerBlocked(BaseModel):
    name: str
    reason: str


class RemoveContainerResult(BaseModel):
    ok: bool
    removed: list[str]
    failed: list[RemoveContainerFailure]
    blocked: list[RemoveContainerBlocked] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


async def _run_docker(
    args: list[str], *, cwd: str
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


def _managed_compose_projects(ctx: ToolContext) -> set[str]:
    return {summary.name for summary in ctx.state_store.list()}


async def _block_reason_for_container(
    container_ref: str,
    ctx: ToolContext,
    managed_projects: set[str],
) -> str | None:
    try:
        inspected = await ctx.docker_engine.inspect(container_ref)
    except Exception:
        return None

    project = inspected.config.labels.get("com.docker.compose.project")
    if project and project in managed_projects:
        return (
            f"Container belongs to managed stack '{project}'; "
            "use stop_stack to stop services or destroy_stack to tear down."
        )
    return None


class _RemoveContainerTool:
    name = "remove_container"
    description = (
        "Remove specific orphan Docker containers by exact name or ID — for leftovers "
        "not tracked by destroy_stack. Do NOT bulk-remove all stopped containers. "
        "Containers from stacks managed by docker-agent must use stop_stack or destroy_stack. "
        "Set stopOnly=true to stop without removing."
    )
    input_schema = RemoveContainerInput
    category = "high-level"

    def needs_permission(self, _input: RemoveContainerInput) -> bool:
        return True

    async def call(
        self, input: RemoveContainerInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        removed: list[str] = []
        failed: list[RemoveContainerFailure] = []
        blocked: list[RemoveContainerBlocked] = []
        managed_projects = _managed_compose_projects(ctx)

        for container in input.containers:
            reason = await _block_reason_for_container(container, ctx, managed_projects)
            if reason:
                blocked.append(RemoveContainerBlocked(name=container, reason=reason))
                yield ToolProgress(msg=f"Blocked {container}: {reason}")
                continue

            if input.stop_only:
                yield ToolProgress(msg=f"Stopping {container}...")
                exit_code, _stdout, stderr = await _run_docker(
                    ["stop", container], cwd=ctx.cwd
                )
                if exit_code == 0:
                    removed.append(container)
                else:
                    failed.append(
                        RemoveContainerFailure(
                            name=container, exit_code=exit_code, stderr=stderr.strip()
                        )
                    )
                continue

            if input.force:
                yield ToolProgress(msg=f"Force removing {container}...")
                exit_code, _stdout, stderr = await _run_docker(
                    ["rm", "-f", container], cwd=ctx.cwd
                )
            else:
                yield ToolProgress(msg=f"Stopping {container}...")
                stop_code, _stop_out, stop_err = await _run_docker(
                    ["stop", container], cwd=ctx.cwd
                )
                if stop_code != 0:
                    failed.append(
                        RemoveContainerFailure(
                            name=container,
                            exit_code=stop_code,
                            stderr=stop_err.strip(),
                        )
                    )
                    continue
                yield ToolProgress(msg=f"Removing {container}...")
                exit_code, _stdout, stderr = await _run_docker(
                    ["rm", container], cwd=ctx.cwd
                )

            if exit_code == 0:
                removed.append(container)
            else:
                failed.append(
                    RemoveContainerFailure(
                        name=container, exit_code=exit_code, stderr=stderr.strip()
                    )
                )

        yield ToolDone(
            RemoveContainerResult(
                ok=len(failed) == 0 and len(blocked) == 0 and len(removed) > 0,
                removed=removed,
                failed=failed,
                blocked=blocked,
            )
        )


remove_container = _RemoveContainerTool()

__all__ = [
    "MAX_CONTAINERS_PER_CALL",
    "RemoveContainerBlocked",
    "RemoveContainerFailure",
    "RemoveContainerInput",
    "RemoveContainerResult",
    "remove_container",
]

"""get_logs tool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from docker_mcp_server.config import stack_state_yaml_path
from docker_mcp_server.state.secret_redactor import scrub_line
from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress
from docker_mcp_server.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)
_MAX_BYTES = 16 * 1024


class GetLogsInput(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str = Field(alias="stackName")
    service: str | None = None
    tail_lines: int | None = Field(default=None, alias="tailLines", ge=0, le=1000)
    since: str | None = None


class GetLogsResult(BaseModel):
    model_config = _MODEL_CONFIG

    log_tail: str = Field(alias="logTail")
    line_count: int = Field(alias="lineCount")
    truncated: bool
    error: str | None = None


def _cap_newest(lines: list[str]) -> tuple[str, bool]:
    """Keep the newest lines so total UTF-8 size stays <= MAX_BYTES."""
    total = 0
    kept: list[str] = []
    truncated = False
    for line in reversed(lines):
        size = len(line.encode("utf-8"))
        if total + size > _MAX_BYTES:
            truncated = True
            break
        total += size
        kept.append(line)
    kept.reverse()
    return "".join(kept), truncated


class GetLogsTool:
    name = "get_logs"
    description = (
        "Fetch a bounded snapshot of a stack's logs for diagnosis "
        "(read-only, secrets redacted)."
    )
    input_schema = GetLogsInput
    category = "read-only"

    def needs_permission(self, _input: GetLogsInput) -> bool:
        return False

    async def call(
        self, input: GetLogsInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yaml_path = stack_state_yaml_path(input.stack_name, ctx.cwd)
        if not Path(yaml_path).exists():
            yield ToolDone(
                GetLogsResult(
                    logTail=f"stack {input.stack_name} not found",
                    lineCount=0,
                    truncated=False,
                )
            )
            return

        yield ToolProgress(msg=f"Fetching logs for {input.stack_name}...")

        try:
            secret_keys = collect_secret_keys(
                input.stack_name,
                SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store),
            )
        except Exception:
            secret_keys = set()

        bound = ctx.compose_runner.for_stack(input.stack_name, yaml_path)

        try:
            scrubbed: list[str] = []
            async for line in bound.logs(
                service=input.service,
                tail_lines=input.tail_lines or 100,
                since=input.since,
            ):
                scrubbed.append(scrub_line(line, secret_keys))

            text, truncated = _cap_newest(scrubbed)
            yield ToolDone(
                GetLogsResult(
                    logTail=text,
                    lineCount=len(scrubbed),
                    truncated=truncated,
                )
            )
        except Exception as error:
            yield ToolDone(
                GetLogsResult(
                    logTail="",
                    lineCount=0,
                    truncated=False,
                    error=str(error),
                )
            )


get_logs = GetLogsTool()

__all__ = [
    "GetLogsInput",
    "GetLogsResult",
    "GetLogsTool",
    "get_logs",
]

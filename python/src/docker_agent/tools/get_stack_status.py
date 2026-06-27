"""get_stack_status tool.

Parity: ``src/tools/getStackStatus.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from docker_agent.config import stack_state_yaml_path
from docker_agent.services.docker.compose_runner import ComposePsRow
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.tool import ToolContext, ToolDone, ToolProgress
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


class GetStackStatusInput(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str = Field(alias="stackName")
    tail_lines: int | None = Field(default=None, alias="tailLines", ge=0, le=1000)


class GetStackStatusResult(BaseModel):
    model_config = _MODEL_CONFIG

    rows: list[ComposePsRow]
    log_tail: str = Field(alias="logTail")


class GetStackStatusTool:
    name = "get_stack_status"
    description = (
        "Show container state, health, ports, and last log lines for a stack."
    )
    input_schema = GetStackStatusInput
    category = "read-only"

    def needs_permission(self, _input: GetStackStatusInput) -> bool:
        return False

    async def call(
        self, input: GetStackStatusInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yaml_path = stack_state_yaml_path(input.stack_name, ctx.cwd)
        if not Path(yaml_path).exists():
            yield ToolDone(
                GetStackStatusResult(
                    rows=[],
                    logTail=f"stack {input.stack_name} not found",
                )
            )
            return

        yield ToolProgress(msg=f"Compose ps + logs for {input.stack_name}...")
        secret_keys = collect_secret_keys(
            input.stack_name,
            SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store),
        )
        bound = ctx.compose_runner.for_stack(input.stack_name, yaml_path)
        rows = await bound.ps(json=True)
        log_tail = ""
        async for line in bound.logs(tail_lines=input.tail_lines or 50):
            log_tail += scrub_line(line, secret_keys)

        yield ToolDone(GetStackStatusResult(rows=rows, logTail=log_tail))


get_stack_status = GetStackStatusTool()

__all__ = [
    "GetStackStatusInput",
    "GetStackStatusResult",
    "GetStackStatusTool",
    "get_stack_status",
]
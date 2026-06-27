"""destroy_stack tool.

Parity: ``src/tools/destroyStack.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import stack_state_yaml_path
from src.state.state_store import HistoryEvent
from src.tool import ToolContext, ToolDone, ToolProgress


class DestroyStackInput(BaseModel):
    stack_name: str = Field(alias="stackName")
    remove_volumes: bool | None = Field(default=None, alias="removeVolumes")

    model_config = {"populate_by_name": True}


class DestroyStackResult(BaseModel):
    ok: bool
    exit_code: int = Field(alias="exitCode")

    model_config = {"populate_by_name": True}


class _DestroyStackTool:
    name = "destroy_stack"
    description = (
        "Tear down a stack via Compose down (optionally with volumes) and archive its state."
    )
    input_schema = DestroyStackInput
    category = "high-level"

    def needs_permission(self, _input: DestroyStackInput) -> bool:
        return True

    async def call(
        self, input: DestroyStackInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yaml_path = stack_state_yaml_path(input.stack_name, ctx.cwd)
        if not Path(yaml_path).exists():
            yield ToolProgress(msg=f"No stack file for {input.stack_name}; nothing to do.")
            yield ToolDone(DestroyStackResult(ok=True, exit_code=0))
            return

        yield ToolProgress(msg=f"Compose down for {input.stack_name}...")
        bound = ctx.compose_runner.for_stack(input.stack_name, yaml_path)
        async for line in bound.down(volumes=bool(input.remove_volumes)):
            yield ToolProgress(msg=line.rstrip())
        exit_code = getattr(bound, "last_exit_code", 0)

        ctx.state_store.remove(input.stack_name)
        ctx.state_store.append_history(
            HistoryEvent(
                ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                session_id="unknown",
                stack_name=input.stack_name,
                action="destroy",
                details={
                    "removeVolumes": input.remove_volumes or False,
                    "exitCode": exit_code,
                },
            )
        )
        yield ToolDone(DestroyStackResult(ok=exit_code == 0, exit_code=exit_code))


destroy_stack = _DestroyStackTool()

__all__ = ["DestroyStackInput", "DestroyStackResult", "destroy_stack"]
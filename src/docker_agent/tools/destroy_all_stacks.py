"""destroy_all_stacks tool.

Parity: ``src/tools/destroyAllStacks.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel, Field

from docker_agent.tools.base import ToolContext, ToolDone, ToolProgress
from docker_agent.tools.destroy_stack import DestroyStackInput, destroy_stack


class DestroyAllStacksInput(BaseModel):
    remove_volumes: bool | None = Field(default=None, alias="removeVolumes")

    model_config = {"populate_by_name": True}


class DestroyStackFailure(BaseModel):
    stack: str
    exit_code: int = Field(alias="exitCode")

    model_config = {"populate_by_name": True}


class DestroyAllStacksResult(BaseModel):
    destroyed: list[str]
    failed: list[DestroyStackFailure]


class _DestroyAllStacksTool:
    name = "destroy_all_stacks"
    description = (
        "Tear down ALL stacks. Requires typed DESTROY ALL confirmation handled by L3 "
        "before invocation."
    )
    input_schema = DestroyAllStacksInput
    category = "high-level"

    def needs_permission(self, _input: DestroyAllStacksInput) -> bool:
        return True

    async def call(
        self, input: DestroyAllStacksInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        destroyed: list[str] = []
        failed: list[DestroyStackFailure] = []

        for stack in ctx.state_store.list():
            yield ToolProgress(msg=f"Destroying {stack.name}...")
            gen = destroy_stack.call(
                DestroyStackInput(
                    stack_name=stack.name,
                    remove_volumes=input.remove_volumes,
                ),
                ctx,
            )
            outcome_ok = False
            exit_code = -1
            try:
                async for item in gen:
                    if isinstance(item, ToolDone):
                        outcome_ok = item.result.ok
                        exit_code = item.result.exit_code
                    else:
                        yield item
            except Exception as err:  # noqa: BLE001
                yield ToolProgress(msg=f"Failed to destroy {stack.name}: {err}")

            if outcome_ok:
                destroyed.append(stack.name)
            else:
                failed.append(DestroyStackFailure(stack=stack.name, exit_code=exit_code))

        yield ToolDone(DestroyAllStacksResult(destroyed=destroyed, failed=failed))


destroy_all_stacks = _DestroyAllStacksTool()

__all__ = [
    "DestroyAllStacksInput",
    "DestroyAllStacksResult",
    "destroy_all_stacks",
]
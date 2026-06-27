"""list_stacks tool.

Parity: ``src/tools/listStacks.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict

from src.tool import ToolContext, ToolDone, ToolProgress
from src.types.stack import StackSummary

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


class ListStacksInput(BaseModel):
    model_config = _MODEL_CONFIG


class ListStacksResult(BaseModel):
    model_config = _MODEL_CONFIG

    stacks: list[StackSummary]


class ListStacksTool:
    name = "list_stacks"
    description = "List all stacks defined under .docker-agent/states/."
    input_schema = ListStacksInput
    category = "read-only"

    def needs_permission(self, _input: ListStacksInput) -> bool:
        return False

    async def call(
        self, _input: ListStacksInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg="Listing stacks...")
        yield ToolDone(ListStacksResult(stacks=ctx.state_store.list()))


list_stacks = ListStacksTool()

__all__ = [
    "ListStacksInput",
    "ListStacksResult",
    "ListStacksTool",
    "list_stacks",
]
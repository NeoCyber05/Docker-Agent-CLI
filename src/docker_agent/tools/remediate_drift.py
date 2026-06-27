"""remediate_drift tool.

Parity: ``src/tools/remediateDrift.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import yaml
from pydantic import BaseModel, Field

from docker_agent.state.drift_detector import detect_drift
from docker_agent.tool import ToolContext, ToolDone, ToolProgress
from docker_agent.types.stack import StackDiff


class RemediateDriftInput(BaseModel):
    stack_name: str = Field(alias="stackName", min_length=1)

    model_config = {"populate_by_name": True}


class RemediateDriftResult(BaseModel):
    diff: StackDiff
    desired_yaml: str = Field(alias="desiredYaml")
    remediable: bool
    reason: str | None = None

    model_config = {"populate_by_name": True}


class _RemediateDriftTool:
    name = "remediate_drift"
    description = (
        "Detect configuration drift for a stack and return the desired state for remediation. "
        "The caller (L3) handles confirmation and re-apply."
    )
    input_schema = RemediateDriftInput
    category = "high-level"

    def needs_permission(self, _input: RemediateDriftInput) -> bool:
        return True

    async def call(
        self, input: RemediateDriftInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg=f"Detecting drift for stack {input.stack_name}...")
        diff = await detect_drift(
            input.stack_name, ctx.state_store, ctx.docker_engine, ctx.cwd
        )

        if diff.status == "in_sync":
            yield ToolDone(
                RemediateDriftResult(
                    diff=diff,
                    desired_yaml="",
                    remediable=False,
                    reason="in_sync",
                )
            )
            return

        definition = ctx.state_store.read(input.stack_name)
        if definition is None:
            yield ToolDone(
                RemediateDriftResult(
                    diff=diff,
                    desired_yaml="",
                    remediable=False,
                    reason="no desired state",
                )
            )
            return

        desired_yaml = yaml.safe_dump(
            definition.model_dump(by_alias=True),
            sort_keys=False,
        )
        yield ToolDone(
            RemediateDriftResult(
                diff=diff,
                desired_yaml=desired_yaml,
                remediable=True,
            )
        )


remediate_drift = _RemediateDriftTool()

__all__ = ["RemediateDriftInput", "RemediateDriftResult", "remediate_drift"]
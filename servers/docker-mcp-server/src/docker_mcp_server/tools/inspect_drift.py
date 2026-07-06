"""inspect_drift tool.

Parity: ``src/tools/inspectDrift.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from docker_mcp_server.state.drift_detector import detect_drift
from docker_mcp_server.state.state_store import HistoryEvent
from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


class InspectDriftInput(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str = Field(alias="stackName")


class InspectDriftTool:
    name = "inspect_drift"
    description = (
        "Compare desired state (stack YAML) with actual state (live containers)."
    )
    input_schema = InspectDriftInput
    category = "read-only"

    def needs_permission(self, _input: InspectDriftInput) -> bool:
        return False

    async def call(
        self, input: InspectDriftInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg=f"Inspecting drift for {input.stack_name}...")
        result = await detect_drift(
            input.stack_name,
            ctx.state_store,
            ctx.docker_engine,
            ctx.cwd,
        )
        if result.status != "in_sync":
            ctx.state_store.append_history(
                HistoryEvent(
                    ts=datetime.now(UTC).isoformat(),
                    session_id=ctx.session_id or "unknown",
                    stack_name=input.stack_name,
                    action="drift_detected",
                    details={"status": result.status},
                )
            )
        yield ToolDone(result)


inspect_drift = InspectDriftTool()

__all__ = ["InspectDriftInput", "InspectDriftTool", "inspect_drift"]


"""Drain a Tool call into a ToolRun.

Parity: ``src/backend/langgraph/adapters/toolAdapter.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docker_agent.tools.base import Tool, ToolDone, ToolProgress


@dataclass
class ToolRun:
    progress: list[ToolProgress]
    output: Any
    is_error: bool


async def run_tool(tool: Tool[Any, Any], input: Any, ctx: Any) -> ToolRun:
    progress: list[ToolProgress] = []
    gen = tool.call(input, ctx)
    output: Any = None
    async for item in gen:
        if isinstance(item, ToolDone):
            output = item.result
        else:
            progress.append(item)
    return ToolRun(progress=progress, output=output, is_error=False)
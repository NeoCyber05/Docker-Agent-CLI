"""Drain a generic async tool call into a ToolRun."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolRun:
    progress: list[Any]
    output: Any
    is_error: bool


async def run_tool(tool: Any, input: Any, ctx: Any) -> ToolRun:
    progress: list[Any] = []
    output: Any = None
    async for item in tool.call(input, ctx):
        if hasattr(item, "result") and item.__class__.__name__ == "ToolDone":
            output = item.result
        else:
            progress.append(item)
    return ToolRun(progress=progress, output=output, is_error=False)


__all__ = ["ToolRun", "run_tool"]

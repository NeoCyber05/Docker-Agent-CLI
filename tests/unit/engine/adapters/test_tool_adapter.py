import pytest

from docker_agent.engine.adapters.tool_adapter import run_tool
from docker_agent.tools.base import ToolContext, ToolDone, ToolProgress


class EchoTool:
    name = "echo"

    async def call(self, input: str, ctx: ToolContext):
        yield ToolProgress(msg="working")
        yield ToolDone(result=input)


@pytest.mark.asyncio
async def test_run_tool_captures_progress_and_output(make_tool_ctx) -> None:
    ctx = make_tool_ctx()
    run = await run_tool(EchoTool(), "hi", ctx)
    assert [p.msg for p in run.progress] == ["working"]
    assert run.output == "hi"
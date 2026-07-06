import pytest

from docker_agent.engine.adapters.tool_adapter import run_tool


class ToolProgress:
    def __init__(self, msg: str) -> None:
        self.msg = msg


class ToolDone:
    def __init__(self, result: object) -> None:
        self.result = result


class EchoTool:
    name = "echo"

    async def call(self, input: str, ctx: object):
        yield ToolProgress(msg="working")
        yield ToolDone(result=input)


@pytest.mark.asyncio
async def test_run_tool_captures_progress_and_output(make_tool_ctx) -> None:
    ctx = make_tool_ctx()
    run = await run_tool(EchoTool(), "hi", ctx)
    assert [p.msg for p in run.progress] == ["working"]
    assert run.output == "hi"


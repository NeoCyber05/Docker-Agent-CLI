from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from tests.unit.engine.langgraph.test_mcp_control_plane import (
    ToolCallingFakeModel,
    _FakeMcpTool,
    _run_mcp_backend,
)


@pytest.mark.asyncio
async def test_langchain_backend_uses_mcp_tools_when_flag_enabled(
    make_loop_ctx, tmp_project, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_MCP", "1")

    @tool("docker.list_stacks")
    async def mcp_list_stacks() -> str:
        """List stacks through MCP."""

        return "[]"

    model = ToolCallingFakeModel(responses=[AIMessage(content="done")])

    events = await _run_mcp_backend(ctx=ctx, model=model, tools=[mcp_list_stacks])

    assert [tool.name for tool in model.bound_tools] == ["docker.list_stacks"]
    assert any(getattr(e, "delta", "") == "done" for e in events)

class _StopArgs(BaseModel):
    stack_name: str



@pytest.mark.asyncio
async def test_mcp_command_router_handles_metadata_command_without_model(
    make_loop_ctx, tmp_project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra_agent.agent import BackendQueryParams
    from infra_agent.engine.langgraph.backend import LangGraphBackend
    from infra_agent.types.message import UserMessage

    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_MCP", "1")
    capabilities = _FakeMcpTool(
        "docker.capabilities",
        {
            "commands": [
                {
                    "pattern": r"^stop (?P<stack_name>\S+)$",
                    "tool": "docker.stop_stack",
                    "confirmation": "permission",
                    "args": {"stack_name": "$stack_name"},
                }
            ],
            "tools": [
                {
                    "name": "docker.stop_stack",
                    "risk": "high",
                    "mutating": True,
                }
            ],
        },
    )
    stop = _FakeMcpTool("docker.stop_stack", {"status": "ok"}, _StopArgs)

    with (
        patch(
            "infra_agent.engine.langgraph.runtime.load_mcp_langchain_tools",
            AsyncMock(return_value=[capabilities, stop]),
        ),
        patch(
            "infra_agent.engine.langgraph.runtime.create_chat_model",
            side_effect=AssertionError("agent node should not run"),
        ),
    ):
        events = [
            event
            async for event in LangGraphBackend().query(
                BackendQueryParams.model_construct(
                    messages=[UserMessage(content="stop web")],
                    ctx=ctx,
                    provider=type("Provider", (), {"name": "fake"})(),
                    model="fake-model",
                )
            )
        ]

    assert not any(getattr(event, "type", None) == "error" for event in events)
    assert stop.calls == [
        {
            "stack_name": "web",
            "cwd": ctx.cwd,
            "session_id": "default",
            "provider_name": "fake",
            "model": "fake-model",
        }
    ]

from __future__ import annotations

from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from infra_agent.agent import BackendQueryParams
from infra_agent.config import UserConfig
from infra_agent.core.loop_context import ActionReviewPayload
from infra_agent.engine.langgraph.backend import LangGraphBackend
from infra_agent.types.message import UserMessage


class ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        object.__setattr__(self, "bound_tools", tools)
        return self


class _FakeMcpTool:
    description = "fake MCP tool"

    def __init__(
        self,
        name: str,
        result: object,
        args_schema: type[BaseModel] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.result = result
        self.args_schema = args_schema
        self.metadata = metadata or {}
        self.calls: list[object] = []

    async def ainvoke(self, input_data: object) -> object:
        self.calls.append(input_data)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


async def _run_mcp_backend(
    *,
    ctx: Any,
    model: ToolCallingFakeModel,
    tools: list[_FakeMcpTool],
) -> list[object]:
    backend = LangGraphBackend()
    events: list[object] = []
    env = patch.dict("os.environ", {"DOCKER_AGENT_MCP": "1"})
    with (
        env,
        patch(
            "infra_agent.engine.langgraph.runtime.load_user_config",
            return_value=UserConfig(),
        ),
        patch(
            "infra_agent.engine.langgraph.runtime.create_chat_model",
            return_value=model,
        ),
        patch(
            "infra_agent.engine.langgraph.runtime.load_mcp_langchain_tools",
            AsyncMock(return_value=tools),
        ),
        nullcontext(),
    ):
        async for ev in backend.query(
            BackendQueryParams.model_construct(
                messages=[UserMessage(content="run")],
                ctx=ctx,
                provider=type("Provider", (), {"name": "fake"})(),
                model="fake-model",
            )
        ):
            events.append(ev)
    return events


@pytest.mark.asyncio
async def test_mcp_control_plane_executes_read_only_tool_call(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    capabilities = _FakeMcpTool(
        "docker.capabilities",
        {"tools": [{"name": "docker.list_stacks", "operation": "observe"}]},
    )
    list_stacks = _FakeMcpTool("docker.list_stacks", {"stacks": []})
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "docker.list_stacks", "args": {}, "id": "call-list"}],
            ),
            AIMessage(content="done"),
        ]
    )

    events = await _run_mcp_backend(ctx=ctx, model=model, tools=[capabilities, list_stacks])

    assert [tool.name for tool in model.bound_tools] == ["docker.list_stacks"]
    assert list_stacks.calls == [
        {
            "cwd": ctx.cwd,
            "session_id": "default",
            "provider_name": "fake",
            "model": "fake-model",
        }
    ]
    types = [getattr(event, "type", None) for event in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert any(getattr(event, "delta", "") == "done" for event in events)


@pytest.mark.asyncio
async def test_mcp_control_plane_hides_internal_lifecycle_tools(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    capabilities = _FakeMcpTool("docker.capabilities", {"tools": []})
    commit = _FakeMcpTool("docker.commit_action", {"status": "ok"})
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "docker.commit_action", "args": {}, "id": "call-commit"}],
            ),
            AIMessage(content="done"),
        ]
    )

    events = await _run_mcp_backend(ctx=ctx, model=model, tools=[capabilities, commit])

    assert [tool.name for tool in model.bound_tools] == []
    assert commit.calls == []
    assert any("not available" in getattr(event, "delta", "") for event in events)


@pytest.mark.asyncio
async def test_mcp_control_plane_approved_pending_action_calls_commit_tool(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    ctx.request_confirm.return_value = {"kind": "approve"}
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    capabilities = _FakeMcpTool(
        "docker.capabilities",
        {
            "tools": [
                {
                    "name": "docker.deploy_stack",
                    "risk": "high",
                    "mutating": True,
                    "commit_tool": "docker.commit_action",
                    "rollback_tool": "docker.rollback_action",
                }
            ]
        },
    )
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "pending-1",
            "session_id": "default",
            "cwd": ctx.cwd,
            "tool": "docker.deploy_stack",
            "kind": "plan_review",
            "display": {
                "artifacts": [
                    {
                        "kind": "manifest",
                        "label": "Compose YAML",
                        "language": "yaml",
                        "content": "services: {}",
                    },
                    {"kind": "diff", "label": "Stack diff", "content": {"serviceDiffs": []}},
                ]
            },
        },
    }
    deploy = _FakeMcpTool("docker.deploy_stack", pending, metadata={"risk": "high"})
    commit = _FakeMcpTool(
        "docker.commit_action",
        {"status": "ok", "result": "Stack applied.", "ok": True},
    )
    rollback = _FakeMcpTool("docker.rollback_action", {"status": "ok"})
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "docker.deploy_stack", "args": {"stackName": "web"}, "id": "deploy-1"}
                ],
            ),
            AIMessage(content="finished"),
        ]
    )

    events = await _run_mcp_backend(
        ctx=ctx,
        model=model,
        tools=[capabilities, deploy, commit, rollback],
    )

    ctx.request_confirm.assert_awaited_once()
    review = ctx.request_confirm.await_args.args[0]
    assert isinstance(review, ActionReviewPayload)
    assert review.pending_action_id == "pending-1"
    assert review.tool == "docker.deploy_stack"
    assert [artifact.kind for artifact in review.artifacts] == ["manifest", "diff"]
    assert len(deploy.calls) == 1
    assert commit.calls == [
        {
            "pending_action_id": "pending-1",
            "session_id": "default",
            "cwd": ctx.cwd,
            "decision": "approve",
            "typed_phrase": None,
            "secrets": None,
        }
    ]
    assert rollback.calls == []
    assert any(getattr(event, "delta", "") == "finished" for event in events)


@pytest.mark.asyncio
async def test_mcp_control_plane_failed_commit_calls_rollback_tool(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    ctx.request_confirm.return_value = {"kind": "approve"}
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    capabilities = _FakeMcpTool(
        "docker.capabilities",
        {
            "tools": [
                {
                    "name": "docker.deploy_stack",
                    "risk": "high",
                    "mutating": True,
                    "commit_tool": "docker.commit_action",
                    "rollback_tool": "docker.rollback_action",
                }
            ]
        },
    )
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "pending-2",
            "session_id": "default",
            "cwd": ctx.cwd,
            "tool": "docker.deploy_stack",
            "kind": "plan_review",
            "display": {
                "artifacts": [
                    {
                        "kind": "manifest",
                        "label": "Compose YAML",
                        "language": "yaml",
                        "content": "services: {}",
                    },
                    {"kind": "diff", "label": "Stack diff", "content": {"serviceDiffs": []}},
                ]
            },
        },
    }
    deploy = _FakeMcpTool("docker.deploy_stack", pending, metadata={"risk": "high"})
    commit = _FakeMcpTool(
        "docker.commit_action",
        {
            "status": "error",
            "ok": False,
            "result": "apply failed",
            "rollback_action": {"id": "rollback-1", "tool": "docker.rollback_action"},
        },
    )
    rollback = _FakeMcpTool(
        "docker.rollback_action",
        {"status": "ok", "ok": True, "result": "rollback succeeded"},
    )
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "docker.deploy_stack", "args": {"stackName": "web"}, "id": "deploy-1"}
                ],
            ),
            AIMessage(content="finished"),
        ]
    )

    await _run_mcp_backend(ctx=ctx, model=model, tools=[capabilities, deploy, commit, rollback])

    assert commit.calls
    assert rollback.calls == [
        {
            "rollback_action_id": "rollback-1",
            "session_id": "default",
            "cwd": ctx.cwd,
        }
    ]


@pytest.mark.asyncio
async def test_mcp_control_plane_handles_second_plugin_pending_action(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    ctx.request_confirm.return_value = {"kind": "approve"}
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    docker_capabilities = _FakeMcpTool(
        "docker.capabilities",
        {
            "tools": [
                {"namespace": "docker", "name": "docker.list_stacks", "operation": "observe"},
            ],
            "context": {"summarize_tool": "docker.summarize_context"},
        },
    )
    k8s_capabilities = _FakeMcpTool(
        "k8s.capabilities",
        {
            "tools": [
                {
                    "namespace": "k8s",
                    "name": "k8s.deploy",
                    "risk": "high",
                    "mutating": True,
                    "commit_tool": "k8s.commit_action",
                    "rollback_tool": "k8s.rollback_action",
                },
                {
                    "namespace": "k8s",
                    "name": "k8s.commit_action",
                    "operation": "commit",
                    "model_visible": False,
                },
                {
                    "namespace": "k8s",
                    "name": "k8s.rollback_action",
                    "operation": "rollback",
                    "model_visible": False,
                },
            ],
            "commands": [
                {
                    "pattern": r"^pods$",
                    "tool": "k8s.list_pods",
                    "confirmation": "none",
                    "args": {},
                }
            ],
            "context": {"summarize_tool": "k8s.summarize_context"},
        },
    )
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "k8s-pending-1",
            "session_id": "default",
            "cwd": ctx.cwd,
            "tool": "k8s.deploy",
            "kind": "plan_review",
            "display": {
                "title": "Review Kubernetes deployment",
                "summary": "Create deployment web.",
                "artifacts": [
                    {
                        "kind": "manifest",
                        "label": "Deployment",
                        "language": "yaml",
                        "content": "kind: Deployment\n",
                    }
                ],
            },
        },
    }
    docker_list = _FakeMcpTool("docker.list_stacks", {"stacks": []})
    k8s_deploy = _FakeMcpTool("k8s.deploy", pending, metadata={"risk": "high"})
    k8s_commit = _FakeMcpTool("k8s.commit_action", {"status": "ok", "ok": True})
    k8s_rollback = _FakeMcpTool("k8s.rollback_action", {"status": "ok"})
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "k8s.deploy", "args": {"name": "web"}, "id": "k8s-1"}],
            ),
            AIMessage(content="finished"),
        ]
    )

    events = await _run_mcp_backend(
        ctx=ctx,
        model=model,
        tools=[
            docker_capabilities,
            k8s_capabilities,
            docker_list,
            k8s_deploy,
            k8s_commit,
            k8s_rollback,
        ],
    )

    assert [tool.name for tool in model.bound_tools] == ["docker.list_stacks", "k8s.deploy"]
    ctx.request_confirm.assert_awaited_once()
    review = ctx.request_confirm.await_args.args[0]
    assert isinstance(review, ActionReviewPayload)
    assert review.pending_action_id == "k8s-pending-1"
    assert review.tool == "k8s.deploy"
    assert review.artifacts[0].kind == "manifest"
    assert k8s_commit.calls == [
        {
            "pending_action_id": "k8s-pending-1",
            "session_id": "default",
            "cwd": ctx.cwd,
            "decision": "approve",
            "typed_phrase": None,
            "secrets": None,
        }
    ]
    assert k8s_rollback.calls == []
    assert any(getattr(event, "delta", "") == "finished" for event in events)


@pytest.mark.asyncio
async def test_mcp_control_plane_uses_plugin_rollback_tool_from_payload(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    ctx.request_confirm.return_value = {"kind": "approve"}
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    capabilities = _FakeMcpTool(
        "k8s.capabilities",
        {
            "tools": [
                {
                    "namespace": "k8s",
                    "name": "k8s.deploy",
                    "risk": "high",
                    "mutating": True,
                    "commit_tool": "k8s.commit_action",
                    "rollback_tool": "k8s.rollback_action",
                }
            ]
        },
    )
    deploy = _FakeMcpTool(
        "k8s.deploy",
        {
            "status": "pending_confirmation",
            "pending_action": {
                "id": "pending-k8s-rollback",
                "session_id": "default",
                "cwd": ctx.cwd,
                "tool": "k8s.deploy",
                "kind": "plan_review",
                "display": {"title": "Review", "summary": "Review", "artifacts": []},
            },
        },
    )
    commit = _FakeMcpTool(
        "k8s.commit_action",
        {
            "status": "error",
            "ok": False,
            "rollback_action": {"id": "rollback-k8s-1", "tool": "k8s.rollback_action"},
        },
    )
    rollback = _FakeMcpTool("k8s.rollback_action", {"status": "ok", "ok": True})
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "k8s.deploy", "args": {}, "id": "deploy-k8s"}],
            ),
            AIMessage(content="finished"),
        ]
    )

    await _run_mcp_backend(ctx=ctx, model=model, tools=[capabilities, deploy, commit, rollback])

    assert rollback.calls == [
        {
            "rollback_action_id": "rollback-k8s-1",
            "session_id": "default",
            "cwd": ctx.cwd,
        }
    ]

"""Tests for the native LangChain backend path."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from docker_agent.agent import BackendQueryParams
from docker_agent.config import UserConfig
from docker_agent.engine.langgraph_backend import LangGraphBackend
from docker_agent.engine.nodes.apply_with_rollback import ApplyWithRollbackResult
from docker_agent.tools.plan_stack import PlanStackResultOk
from docker_agent.types.message import UserMessage

_DEPLOY_ARGS = {
    "stackName": "web",
    "intent": "deploy nginx",
    "services": [
        {
            "name": "web",
            "kind": "catalog",
            "catalogId": "nginx:1.27",
            "exposure": "public",
        }
    ],
}


class ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        object.__setattr__(self, "bound_tools", tools)
        return self


async def _run_backend(ctx, model: ToolCallingFakeModel) -> list[object]:
    backend = LangGraphBackend()
    events: list[object] = []
    with (
        patch(
            "docker_agent.engine.langgraph_backend.load_user_config",
            return_value=UserConfig(),
        ),
        patch(
            "docker_agent.engine.langgraph_backend.create_chat_model",
            return_value=model,
        ),
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
async def test_langchain_backend_executes_native_tool_call(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "list_stacks", "args": {}, "id": "call-list"}],
            ),
            AIMessage(content="done"),
        ]
    )

    events = await _run_backend(ctx, model)

    assert [tool.name for tool in model.bound_tools if tool.name == "list_stacks"]
    types = [getattr(e, "type", None) for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert any(getattr(e, "delta", "") == "done" for e in events)


@pytest.mark.asyncio
async def test_internal_tool_call_is_not_executed(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "pull_image",
                        "args": {"image": "nginx:1.27"},
                        "id": "call-pull",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )

    events = await _run_backend(ctx, model)

    assert "pull_image" not in {tool.name for tool in model.bound_tools}
    assert ctx.docker_engine.pull_image_calls == []
    assert ctx.request_permission.await_count == 0
    assert any(getattr(e, "delta", "") == "done" for e in events)


@pytest.mark.asyncio
async def test_multiple_high_impact_tool_calls_are_rejected(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "deploy_stack", "args": _DEPLOY_ARGS, "id": "deploy-1"},
                    {"name": "deploy_stack", "args": _DEPLOY_ARGS, "id": "deploy-2"},
                ],
            )
        ]
    )

    events = await _run_backend(ctx, model)

    assert ctx.request_confirm.await_count == 0
    assert not any(getattr(e, "type", None) == "tool_call" for e in events)
    assert any(
        "Only one high-risk tool may be called" in getattr(e, "delta", "")
        for e in events
    )


@pytest.mark.asyncio
async def test_deploy_stack_approval_applies_after_preview(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "deploy_stack", "args": _DEPLOY_ARGS, "id": "deploy-1"}
                ],
            ),
            AIMessage(content="finished"),
        ]
    )
    plan_result = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="abc123",
    )
    apply = AsyncMock(return_value=ApplyWithRollbackResult(ok=True, result_message="applied"))

    with (
        patch(
            "docker_agent.tools.langchain_registry._run_plan_stack",
            AsyncMock(return_value=plan_result),
        ),
        patch(
            "docker_agent.engine.nodes.apply_with_rollback.run_apply_with_rollback",
            apply,
        ),
    ):
        events = await _run_backend(ctx, model)

    preview = ctx.request_confirm.await_args.args[0]
    assert preview["compose_yaml"] == plan_result.compose_yaml
    assert preview["hash"] == "abc123"
    assert apply.await_count == 1
    assert any(getattr(e, "delta", "") == "finished" for e in events)


@pytest.mark.asyncio
async def test_deploy_stack_reject_does_not_apply(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    ctx.request_confirm.return_value = {"kind": "deny"}
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "deploy_stack", "args": _DEPLOY_ARGS, "id": "deploy-1"}
                ],
            ),
            AIMessage(content="finished"),
        ]
    )
    plan_result = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="abc123",
    )
    apply = AsyncMock(return_value=ApplyWithRollbackResult(ok=True, result_message="applied"))

    with (
        patch(
            "docker_agent.tools.langchain_registry._run_plan_stack",
            AsyncMock(return_value=plan_result),
        ),
        patch(
            "docker_agent.engine.nodes.apply_with_rollback.run_apply_with_rollback",
            apply,
        ),
    ):
        await _run_backend(ctx, model)

    assert ctx.request_confirm.await_count == 1
    assert apply.await_count == 0
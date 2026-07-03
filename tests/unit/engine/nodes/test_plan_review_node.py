"""Tests for plan_review_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from docker_agent.engine.nodes.plan_review_node import (
    PlanReviewNodeDeps,
    plan_review_node,
)
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.tools.plan_stack import PlanStackResultBlocked
from docker_agent.tools.validate_spec import SpecIssue
from docker_agent.types.message import AssistantBlock, AssistantMessage


def _plan_state(input_data: dict[str, object]) -> AgentState:
    block = AssistantBlock.model_validate(
        {"type": "tool_use", "id": "t-plan", "name": "plan_stack", "input": input_data}
    )
    return AgentState(messages=[AssistantMessage(content=[block])], iter=1)


@pytest.mark.asyncio
async def test_plan_review_blocked_invalid_spec(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = PlanReviewNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    blocked = PlanStackResultBlocked(
        reason="invalid_spec",
        issues=[SpecIssue(code="x", path="services.web", message="missing image")],
    )

    with patch(
        "docker_agent.engine.nodes.plan_review_node._run_plan_stack",
        new=AsyncMock(return_value=blocked),
    ):
        result = await plan_review_node(
            deps,
            _plan_state(
                {
                    "stackName": "bad",
                    "intent": "bad",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:latest",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        )

    assert result["messages"][0].is_error is True
    assert "Specification is invalid" in result["messages"][0].content


@pytest.mark.asyncio
async def test_plan_review_policy_deny(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = PlanReviewNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)
    violation = type(
        "Violation",
        (),
        {
            "service": "web",
            "rule": "privileged_containers",
            "message": "no",
        },
    )()
    policy.evaluate = lambda _yaml: [violation]  # type: ignore[method-assign]

    from docker_agent.tools.plan_stack import PlanStackResultOk
    from docker_agent.types.stack import StackDiff

    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx\n    privileged: true\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="abc",
    )

    with patch(
        "docker_agent.engine.nodes.plan_review_node._run_plan_stack",
        new=AsyncMock(return_value=ok_plan),
    ):
        result = await plan_review_node(
            deps,
            _plan_state(
                {
                    "stackName": "web",
                    "intent": "deploy",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:latest",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        )

    assert result["messages"][0].is_error is True
    assert "Policy violation" in result["messages"][0].content


@pytest.mark.asyncio
async def test_plan_review_success_with_apply(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = PlanReviewNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    from docker_agent.engine.nodes.apply_with_rollback import ApplyWithRollbackResult
    from docker_agent.tools.plan_stack import PlanStackResultOk
    from docker_agent.types.stack import StackDiff

    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27-alpine\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="abc",
    )

    with (
        patch(
            "docker_agent.engine.nodes.plan_review_node._run_plan_stack",
            new=AsyncMock(return_value=ok_plan),
        ),
        patch(
            "docker_agent.engine.nodes.plan_review_node.interrupt",
            return_value={"kind": "approve"},
        ),
        patch(
            "docker_agent.engine.nodes.plan_review_node.run_apply_with_rollback",
            new=AsyncMock(
                return_value=ApplyWithRollbackResult(ok=True, result_message="Stack applied.")
            ),
        ),
    ):
        result = await plan_review_node(
            deps,
            _plan_state(
                {
                    "stackName": "web",
                    "intent": "deploy",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        )

    assert result["messages"][0].content == "Stack applied."


@pytest.mark.asyncio
async def test_plan_review_appends_plan_history_before_interrupt(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    ctx.session_id = "sess-plan"
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = PlanReviewNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    from docker_agent.tools.plan_stack import PlanStackResultOk
    from docker_agent.types.stack import StackDiff

    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27-alpine\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="plan-hash",
    )

    with (
        patch(
            "docker_agent.engine.nodes.plan_review_node._run_plan_stack",
            new=AsyncMock(return_value=ok_plan),
        ),
        patch(
            "docker_agent.engine.nodes.plan_review_node.interrupt",
            return_value={"kind": "deny"},
        ),
        patch.object(
            ctx.state_store, "append_history", wraps=ctx.state_store.append_history
        ) as append_history,
    ):
        await plan_review_node(
            deps,
            _plan_state(
                {
                    "stackName": "web",
                    "intent": "deploy",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        )

    plan_events = [
        call.args[0] for call in append_history.call_args_list if call.args[0].action == "plan"
    ]
    assert plan_events
    assert plan_events[0].session_id == "sess-plan"
    assert plan_events[0].details == {"hash": "plan-hash"}


@pytest.mark.asyncio
async def test_plan_review_requests_secrets_for_missing_required_env(
    make_loop_ctx, tmp_project
) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = PlanReviewNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    from docker_agent.tools.plan_stack import PlanStackResultBlocked, PlanStackResultOk
    from docker_agent.types.stack import StackDiff

    blocked = PlanStackResultBlocked(
        reason="missing_required_env",
        missing_by_service={"db": ["MONGO_INITDB_ROOT_PASSWORD"]},
    )
    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  db:\n    image: mongo:6.0\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="abc",
    )

    ctx.request_secrets_input = AsyncMock(
        return_value={"kind": "secrets_input_values", "values": {"MONGO_INITDB_ROOT_PASSWORD": "user-secret"}}
    )

    with (
        patch(
            "docker_agent.engine.nodes.plan_review_node._run_plan_stack",
            new=AsyncMock(side_effect=[blocked, ok_plan]),
        ),
        patch(
            "docker_agent.engine.nodes.plan_review_node.interrupt",
            return_value={"kind": "deny"},
        ),
    ):
        await plan_review_node(
            deps,
            _plan_state(
                {
                    "stackName": "web",
                    "intent": "deploy",
                    "services": [
                        {
                            "name": "db",
                            "kind": "catalog",
                            "catalogId": "mongodb:6.0",
                        }
                    ],
                }
            ),
        )

    ctx.request_secrets_input.assert_awaited_once_with(
        "db",
        ["MONGO_INITDB_ROOT_PASSWORD"],
        "missing required env",
    )
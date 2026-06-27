"""Tests for plan_review_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.engine.nodes.plan_review_node import (
    PlanReviewNodeDeps,
    plan_review_node,
)
from src.engine.state import AgentState
from src.policy.policy_engine import PolicyEngine
from src.tools.plan_stack import PlanStackResultBlocked
from src.tools.validate_spec import SpecIssue
from src.types.message import AssistantBlock, AssistantMessage


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
        "src.engine.nodes.plan_review_node._run_plan_stack",
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
            "severity": "deny",
            "service": "web",
            "rule": "privileged_containers",
            "message": "no",
        },
    )()
    policy.evaluate = lambda _yaml: [violation]  # type: ignore[method-assign]

    from src.tools.plan_stack import PlanStackResultOk
    from src.types.stack import StackDiff

    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx\n    privileged: true\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="abc",
    )

    with patch(
        "src.engine.nodes.plan_review_node._run_plan_stack",
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

    from src.engine.nodes.apply_with_rollback import ApplyWithRollbackResult
    from src.tools.plan_stack import PlanStackResultOk
    from src.types.stack import StackDiff

    ok_plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27-alpine\n",
        diff=StackDiff(stack_name="web", status="missing", service_diffs=[]),
        hash="abc",
    )

    with (
        patch(
            "src.engine.nodes.plan_review_node._run_plan_stack",
            new=AsyncMock(return_value=ok_plan),
        ),
        patch(
            "src.engine.nodes.plan_review_node.interrupt",
            return_value={"kind": "approve"},
        ),
        patch(
            "src.engine.nodes.plan_review_node.run_apply_with_rollback",
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

    assert result["messages"][0].is_error is False
    assert result["messages"][0].content == "Stack applied."
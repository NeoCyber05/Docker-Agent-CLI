"""Tests for remediate_drift_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from docker_agent.engine.nodes.remediate_drift_node import (
    RemediateDriftNodeDeps,
    remediate_drift_node,
)
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.tools.remediate_drift import RemediateDriftResult
from docker_agent.types.message import AssistantBlock, AssistantMessage
from docker_agent.types.stack import (
    EnvSnapshot,
    FieldChange,
    ServiceDiff,
    ServiceSnapshot,
    StackDiff,
)


def _remediate_state(stack_name: str = "web") -> AgentState:
    block = AssistantBlock.model_validate(
        {
            "type": "tool_use",
            "id": "t-rem",
            "name": "remediate_drift",
            "input": {"stackName": stack_name},
        }
    )
    return AgentState(messages=[AssistantMessage(content=[block])], iter=1)


@pytest.mark.asyncio
async def test_remediate_drift_not_remediable(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = RemediateDriftNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    tool_result = RemediateDriftResult(
        diff=StackDiff(stack_name="web", status="in_sync", service_diffs=[]),
        desired_yaml="",
        remediable=False,
        reason="in_sync",
    )

    async def _gen(*_args, **_kwargs):
        from docker_agent.tool import ToolDone, ToolProgress

        yield ToolProgress(msg="checking")
        yield ToolDone(tool_result)

    with patch(
        "docker_agent.engine.nodes.remediate_drift_node.remediate_drift.call",
        _gen,
    ):
        result = await remediate_drift_node(deps, _remediate_state())

    assert "No remediation needed" in result["messages"][0].content
    assert result["messages"][0].is_error is False


@pytest.mark.asyncio
async def test_remediate_drift_success(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = RemediateDriftNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    tool_result = RemediateDriftResult(
        diff=StackDiff(stack_name="web", status="drift", service_diffs=[]),
        desired_yaml="services:\n  web:\n    image: nginx:1.27-alpine\n",
        remediable=True,
    )

    from docker_agent.engine.nodes.apply_with_rollback import ApplyWithRollbackResult

    async def _gen(*_args, **_kwargs):
        from docker_agent.tool import ToolDone, ToolProgress

        yield ToolProgress(msg="checking")
        yield ToolDone(tool_result)

    with (
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.remediate_drift.call",
            _gen,
        ),
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.interrupt",
            return_value={"kind": "approve"},
        ),
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.run_apply_with_rollback",
            new=AsyncMock(
                return_value=ApplyWithRollbackResult(ok=True, result_message="Stack applied.")
            ),
        ),
    ):
        result = await remediate_drift_node(deps, _remediate_state())

    assert result["messages"][0].is_error is False
    assert result["messages"][0].content == "Stack applied."


@pytest.mark.asyncio
async def test_remediate_drift_orphan_warning(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))
    deps = RemediateDriftNodeDeps(ctx=ctx, policy_engine=policy, emit=lambda _e: None)

    tool_result = RemediateDriftResult(
        diff=StackDiff(
            stack_name="web",
            status="extra",
            service_diffs=[
                ServiceDiff(
                    service="orphan",
                    desired=None,
                    actual=ServiceSnapshot(
                        image="x",
                        ports=[],
                        env=EnvSnapshot(visible={}, secret_keys=[], secret_hashes_by_key={}),
                        volumes=[],
                        replica_count=1,
                    ),
                    changes=[FieldChange(field="image", from_=None, to="x")],
                ),
            ],
        ),
        desired_yaml="services:\n  web:\n    image: nginx:1.27-alpine\n",
        remediable=True,
    )

    from docker_agent.engine.nodes.apply_with_rollback import ApplyWithRollbackResult

    async def _gen(*_args, **_kwargs):
        from docker_agent.tool import ToolDone, ToolProgress

        yield ToolProgress(msg="checking")
        yield ToolDone(tool_result)

    with (
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.remediate_drift.call",
            _gen,
        ),
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.interrupt",
            return_value={"kind": "approve"},
        ),
        patch(
            "docker_agent.engine.nodes.remediate_drift_node.run_apply_with_rollback",
            new=AsyncMock(
                return_value=ApplyWithRollbackResult(ok=True, result_message="Stack applied.")
            ),
        ),
    ):
        result = await remediate_drift_node(deps, _remediate_state())

    assert "orphan service(s)" in result["messages"][0].content
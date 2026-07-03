"""Graph routing tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docker_agent.engine.graph import GraphDeps, build_graph
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.types.message import AssistantBlock, AssistantMessage


def _dual_high_risk_state() -> AgentState:
    return AgentState(
        messages=[
            AssistantMessage(
                content=[
                    AssistantBlock.model_validate(
                        {
                            "type": "tool_use",
                            "id": "t-plan",
                            "name": "plan_stack",
                            "input": {"stackName": "web"},
                        }
                    ),
                    AssistantBlock.model_validate(
                        {
                            "type": "tool_use",
                            "id": "t-remediate",
                            "name": "remediate_drift",
                            "input": {"stackName": "web"},
                        }
                    ),
                ]
            )
        ],
        iter=1,
    )


@pytest.mark.asyncio
async def test_reject_multi_high_risk_tool_calls(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy_path = tmp_project / "project-policies.yaml"
    policy_path.write_text("project: {}\n", encoding="utf-8")
    policy = PolicyEngine(project_policy_path=str(policy_path))

    class FakeProvider:
        name = "fake"

        async def stream(self, _params):
            return
            yield  # pragma: no cover

    graph = build_graph(
        GraphDeps(
            provider=FakeProvider(),
            ctx=ctx,
            model=None,
            emit=lambda _x: None,
            policy_engine=policy,
        )
    )

    async def noop_agent(_deps, _state):
        return {}

    with patch("docker_agent.engine.graph.agent_node", new=noop_agent):
        result = await graph.ainvoke(
            _dual_high_risk_state(),
            {"configurable": {"thread_id": "routing-test"}},
        )

    tool_messages = [m for m in result["messages"] if m.role == "tool"]
    assert len(tool_messages) == 2
    assert all(m.is_error for m in tool_messages)
    assert all("Only one high-risk tool" in m.content for m in tool_messages)

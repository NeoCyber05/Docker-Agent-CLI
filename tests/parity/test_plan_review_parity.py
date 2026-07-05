"""Plan review contract tests for the native LangGraph backend."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from docker_agent.query_engine import QueryEngine
from docker_agent.types.permissions import Approve, Deny
from tests.integration.conftest import FakeProvider, IntegrationFakeModel, deploy_stack_message
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def _make_engine(
    tmp_project: Any,
    state_store: Any,
    compose_runner: MockComposeRunner,
    responses: list[AIMessage],
    monkeypatch: pytest.MonkeyPatch,
) -> QueryEngine:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "langgraph")
    monkeypatch.setenv("DOCKER_AGENT_MCP", "0")
    model_responses = list(responses)
    if model_responses and model_responses[-1].tool_calls:
        model_responses.append(AIMessage(content="done"))
    model = IntegrationFakeModel(responses=model_responses)
    monkeypatch.setattr(
        "docker_agent.engine.langgraph.runtime.create_chat_model",
        lambda **_kwargs: model,
    )
    return QueryEngine(
        cwd=str(tmp_project),
        state_store=state_store,
        docker_engine=MockDockerEngine(),
        compose_runner=compose_runner,
        provider=FakeProvider(),
        model="fake-model",
        health_check_deadline_ms=0,
    )


@pytest.fixture
def plan_review_project(tmp_path: Any):
    (tmp_path / ".docker-agent").mkdir(parents=True)
    (tmp_path / "project-policies.yaml").write_text("project: {}", encoding="utf-8")
    from docker_agent.state.state_store import StateStore

    state_store = StateStore(str(tmp_path / ".docker-agent"))
    compose_runner = MockComposeRunner(str(tmp_path))
    return tmp_path, state_store, compose_runner


@pytest.mark.asyncio
async def test_approve_plan_apply_succeeds(
    plan_review_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_project, state_store, compose_runner = plan_review_project
    compose_runner.on_bound_runner_created = lambda runner: runner.set_running_services(["web"])

    engine = _make_engine(
        tmp_project,
        state_store,
        compose_runner,
        [
            deploy_stack_message(
                {
                    "stackName": "nginx",
                    "intent": "tao nginx",
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
        ],
        monkeypatch,
    )
    events: list[str] = []

    async for ev in engine.query("tao nginx"):
        events.append(ev.type)
        if ev.type == "plan_ready":
            engine.respond_to(ev.id, Approve())

    assert "plan_ready" in events
    assert compose_runner.for_stack_calls[0]["stack_name"] == "nginx"
    assert compose_runner.bound_for("nginx").up_calls[0] == {"detach": True, "scale": None}
    assert (tmp_project / "docker-stacks" / "nginx.yaml").exists()


@pytest.mark.asyncio
async def test_deny_plan_no_apply(
    plan_review_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_project, state_store, compose_runner = plan_review_project
    engine = _make_engine(
        tmp_project,
        state_store,
        compose_runner,
        [
            deploy_stack_message(
                {
                    "stackName": "denied",
                    "intent": "deny me",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        ],
        monkeypatch,
    )
    plan_ready_seen = False

    async for ev in engine.query("deny plan"):
        if ev.type == "plan_ready":
            plan_ready_seen = True
            engine.respond_to(ev.id, Deny())

    assert plan_ready_seen is True
    assert compose_runner.for_stack_calls == []


@pytest.mark.asyncio
async def test_invalid_spec_plan_blocked(
    plan_review_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_project, state_store, compose_runner = plan_review_project
    engine = _make_engine(
        tmp_project,
        state_store,
        compose_runner,
        [
            deploy_stack_message(
                {
                    "stackName": "bad",
                    "intent": "bad spec",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                        }
                    ],
                }
            ),
        ],
        monkeypatch,
    )
    events: list[str] = []

    async for ev in engine.query("bad spec"):
        events.append(ev.type)

    assert "plan_ready" not in events
    assert compose_runner.for_stack_calls == []


@pytest.mark.asyncio
async def test_apply_failure_rollback_events(
    plan_review_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docker_agent.services.docker.compose_runner import ComposePsRow

    tmp_project, state_store, compose_runner = plan_review_project

    def on_bound(runner: Any) -> None:
        async def failing_up(**_kwargs: object):
            yield "partial failure\n"
            runner.last_exit_code = 1

        runner.up = failing_up  # type: ignore[method-assign]
        runner.ps_rows = [ComposePsRow(name="partial-web-1", service="web", state="running")]

    compose_runner.on_bound_runner_created = on_bound

    engine = _make_engine(
        tmp_project,
        state_store,
        compose_runner,
        [
            deploy_stack_message(
                {
                    "stackName": "partial",
                    "intent": "deploy partial",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        },
                        {
                            "name": "db",
                            "kind": "catalog",
                            "catalogId": "postgresql:16",
                        },
                    ],
                }
            ),
        ],
        monkeypatch,
    )

    rollback_events: list[Any] = []

    async for ev in engine.query("deploy partial"):
        if ev.type == "plan_ready":
            engine.respond_to(ev.id, Approve())
        if ev.type in ("rollback_started", "rollback_result"):
            rollback_events.append(ev)

    started = next((e for e in rollback_events if e.type == "rollback_started"), None)
    result = next((e for e in rollback_events if e.type == "rollback_result"), None)
    assert started is not None
    assert started.running_services == ["web"]
    assert "Deploy failed:" in started.detail
    assert "partial failure" in started.detail
    assert "Starting rollback..." in started.detail
    assert result is not None

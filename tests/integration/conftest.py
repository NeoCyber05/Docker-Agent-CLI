"""Shared fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from docker_agent.query_engine import QueryEngine
from docker_agent.state.state_store import StateStore
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


class IntegrationFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        object.__setattr__(self, "bound_tools", tools)
        return self


class FakeProvider:
    name = "fake"


def deploy_stack_message(input_data: object) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "deploy_stack", "args": input_data, "id": "deploy-1"}],
    )


def tool_call_message(name: str, args: object, call_id: str = "tool-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id}],
    )


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True)
    (tmp_path / "project-policies.yaml").write_text("project: {}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def state_store(tmp_project: Path) -> StateStore:
    return StateStore(str(tmp_project / ".docker-agent"))


@pytest.fixture
def compose_runner(tmp_project: Path) -> MockComposeRunner:
    return MockComposeRunner(str(tmp_project))


@pytest.fixture
def make_engine(
    tmp_project: Path,
    state_store: StateStore,
    compose_runner: MockComposeRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    def _make(responses: list[AIMessage]) -> QueryEngine:
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

    return _make
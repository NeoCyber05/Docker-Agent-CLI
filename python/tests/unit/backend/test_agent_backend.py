"""Agent backend factory tests."""

from docker_agent.backend.agent_backend import create_backend


def test_default_backend_is_current(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_BACKEND", raising=False)
    backend = create_backend()
    assert backend.name == "current"


def test_env_selects_langgraph(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "langgraph")
    backend = create_backend()
    assert backend.name == "langgraph"
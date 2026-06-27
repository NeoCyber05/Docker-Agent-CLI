"""Agent backend factory smoke tests (full parity in tests/parity/)."""

from docker_agent.agent import create_backend


def test_default_backend_is_langgraph(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_BACKEND", raising=False)
    backend = create_backend()
    assert backend.name == "langgraph"


def test_env_selects_current(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "current")
    backend = create_backend()
    assert backend.name == "current"


def test_env_selects_langgraph(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "langgraph")
    backend = create_backend()
    assert backend.name == "langgraph"
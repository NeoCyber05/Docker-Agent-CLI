"""Agent backend factory smoke tests."""

from infra_agent.agent import create_backend


def test_default_backend_is_langgraph(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_BACKEND", raising=False)
    backend = create_backend()
    assert backend.name == "langgraph"


def test_env_current_no_longer_selects_legacy_backend(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "current")
    backend = create_backend()
    assert backend.name == "langgraph"


def test_env_selects_langgraph(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_BACKEND", "langgraph")
    backend = create_backend()
    assert backend.name == "langgraph"
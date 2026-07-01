"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["unit.engine.conftest"]


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading the developer's real ~/.docker-agent/config.json in tests."""
    config_path = tmp_path / "user-config.json"
    config_path.write_text('{"provider": "gemini"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(config_path))


@pytest.fixture(autouse=True)
def isolated_global_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading/writing the developer's real ~/.docker-agent/policies.yaml.

    ``PolicyEngine()`` falls back to that path when no ``global_policy_path`` is
    given, and ``ensure_global_policy()`` (called from the CLI/agent-loop
    bootstrap) would otherwise scaffold a real baseline file there — making
    test results depend on whatever happens to exist on the machine running them.

    The isolated file is pre-created *empty* (rather than left missing) so that
    ``ensure_global_policy()`` sees it already exists and does not scaffold the
    full baseline into it — tests that don't care about global policy keep
    seeing zero global rules, matching pre-scaffolding behavior.
    """
    policy_path = tmp_path / "isolated-global-policies.yaml"
    policy_path.write_text("global:\n  hardDeny: []\n  require: []\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_GLOBAL_POLICY", str(policy_path))
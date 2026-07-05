"""Shared Docker MCP server test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading the developer's real ~/.docker-agent/config.json in tests."""
    config_path = tmp_path / "user-config.json"
    config_path.write_text('{"provider": "gemini"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(config_path))


@pytest.fixture(autouse=True)
def isolated_global_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading or writing the developer's real global policy in server tests."""
    policy_path = tmp_path / "isolated-global-policies.yaml"
    policy_path.write_text("global:\n  hardDeny: []\n  require: []\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_GLOBAL_POLICY", str(policy_path))
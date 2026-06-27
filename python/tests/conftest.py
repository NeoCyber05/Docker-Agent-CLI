"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["unit.backend.langgraph.conftest"]


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading the developer's real ~/.docker-agent/config.json in tests."""
    config_path = tmp_path / "user-config.json"
    config_path.write_text('{"provider": "gemini"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(config_path))
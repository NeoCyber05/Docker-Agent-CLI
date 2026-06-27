"""Shared unit-test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid reading the developer's real ~/.docker-agent/config.json in unit tests."""
    config_path = tmp_path / "user-config.json"
    config_path.write_text('{"provider": "gemini"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(config_path))


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    return tmp_path
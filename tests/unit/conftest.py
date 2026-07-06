"""Shared unit-test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / ".docker-agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    return tmp_path

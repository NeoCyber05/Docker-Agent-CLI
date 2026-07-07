"""Dependency contract tests for the Python package metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANGGRAPH_NATIVE_AGENT_RANGE = ">=1.2.5,<1.3"


def _pyproject_dependencies() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(pyproject["project"]["dependencies"])


def _uv_lock_project_requirements() -> list[dict[str, str]]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    infra_agent = next(
        package for package in lock["package"] if package["name"] == "docker-agent"
    )
    return list(infra_agent["metadata"]["requires-dist"])


def test_langgraph_dependency_matches_native_langchain_agent_range() -> None:
    assert f"langgraph{LANGGRAPH_NATIVE_AGENT_RANGE}" in _pyproject_dependencies()


def test_uv_lock_langgraph_metadata_matches_native_langchain_agent_range() -> None:
    requirements = _uv_lock_project_requirements()
    langgraph = next(req for req in requirements if req["name"] == "langgraph")
    assert langgraph["specifier"] == LANGGRAPH_NATIVE_AGENT_RANGE

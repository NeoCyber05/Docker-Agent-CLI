from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_langgraph_runtime_modules_are_split_by_responsibility() -> None:
    for module_name in (
        "infra_agent.engine.langgraph.backend",
        "infra_agent.engine.langgraph.graph",
        "infra_agent.engine.langgraph.state",
        "infra_agent.engine.langgraph.runtime",
        "infra_agent.engine.langgraph.model_factory",
    ):
        importlib.import_module(module_name)


def test_legacy_langgraph_modules_are_removed() -> None:
    for module_name in (
        "infra_agent.engine.langgraph_backend",
        "infra_agent.engine.langgraph_runtime_graph",
        "infra_agent.engine.langchain_model_factory",
    ):
        assert importlib.util.find_spec(module_name) is None


def test_legacy_engine_nodes_package_is_removed() -> None:
    assert not (ROOT / "src" / "infra_agent" / "engine" / "nodes").exists()
    assert importlib.util.find_spec("infra_agent.engine.nodes") is None


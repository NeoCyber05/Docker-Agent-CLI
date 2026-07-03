"""Tests for native LangChain tool exposure."""

from __future__ import annotations

from docker_agent.tools.langchain_registry import get_langchain_tools


def test_langchain_tools_exclude_internal_execution_primitives() -> None:
    tool_names = {tool.name for tool in get_langchain_tools()}

    assert "deploy_stack" in tool_names
    assert "plan_stack" not in tool_names
    assert "apply_stack" not in tool_names
    assert "pull_image" not in tool_names


def test_langchain_tool_schemas_do_not_expose_runtime_context() -> None:
    forbidden = {"ctx", "emit", "runtime"}

    for tool in get_langchain_tools():
        schema = tool.get_input_schema()
        fields = set(getattr(schema, "model_fields", {}))
        assert not (fields & forbidden), tool.name


def test_deploy_stack_is_marked_high_impact() -> None:
    deploy_stack = next(tool for tool in get_langchain_tools() if tool.name == "deploy_stack")

    assert deploy_stack.metadata is not None
    assert deploy_stack.metadata["risk"] == "high"

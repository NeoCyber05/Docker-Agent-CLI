"""Parity tests for docker_agent.tool — mirrors src/Tool.ts."""

from dataclasses import fields

from src.tool import ToolContext, ToolProgress, find_tool_by_name
from src.tools import get_agent_tools


def test_tool_progress_defaults() -> None:
    progress = ToolProgress(msg="hello")
    assert progress.type == "progress"
    assert progress.msg == "hello"


def test_tool_context_fields() -> None:
    field_names = {f.name for f in fields(ToolContext)}
    assert field_names == {
        "cwd",
        "state_store",
        "docker_engine",
        "compose_runner",
        "abort_signal",
        "image_validator",
        "session_id",
        "health_check_deadline_ms",
    }


def test_find_tool_by_name_found() -> None:
    tools = get_agent_tools()
    tool = find_tool_by_name(tools, "validate_spec")
    assert tool is not None
    assert tool.name == "validate_spec"


def test_find_tool_by_name_missing() -> None:
    tools = get_agent_tools()
    assert find_tool_by_name(tools, "nonexistent") is None
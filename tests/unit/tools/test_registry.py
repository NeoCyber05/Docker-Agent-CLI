"""Parity tests for tool registry — mirrors src/tools.ts."""

from docker_agent.tools import get_agent_tools, get_all_tools

AGENT_TOOL_NAMES = [
    "validate_spec",
    "resolve_dependency",
    "check_port_conflict",
    "plan_stack",
    "destroy_stack",
    "destroy_all_stacks",
    "list_stacks",
    "inspect_drift",
    "remediate_drift",
    "get_stack_status",
    "get_logs",
    "get_health",
    "pull_image",
    "exec_docker",
]


def test_agent_tool_names_and_order() -> None:
    assert [t.name for t in get_agent_tools()] == AGENT_TOOL_NAMES


def test_all_tools_includes_apply_stack() -> None:
    assert [t.name for t in get_all_tools()] == AGENT_TOOL_NAMES + ["apply_stack"]


def test_read_only_tools_need_no_permission() -> None:
    for tool in get_agent_tools():
        if tool.category == "read-only":
            assert tool.needs_permission({}) is False


def test_destructive_tools_need_permission() -> None:
    for tool in get_all_tools():
        if tool.name in {
            "destroy_stack",
            "destroy_all_stacks",
            "remediate_drift",
            "apply_stack",
            "pull_image",
            "exec_docker",
        }:
            assert tool.needs_permission({}) is True


def test_plan_stack_does_not_need_permission() -> None:
    tool = next(t for t in get_agent_tools() if t.name == "plan_stack")
    assert tool.needs_permission({}) is False
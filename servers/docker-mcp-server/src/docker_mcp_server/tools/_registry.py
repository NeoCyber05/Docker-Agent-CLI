"""
Tool registry implementation (sibling to the ``tools/`` package).
"""

from __future__ import annotations

from typing import Any

from docker_mcp_server.tools.destroy_all_stacks import destroy_all_stacks
from docker_mcp_server.tools.destroy_stack import destroy_stack
from docker_mcp_server.tools.exec_docker import exec_docker
from docker_mcp_server.tools.get_health import get_health
from docker_mcp_server.tools.get_logs import get_logs
from docker_mcp_server.tools.get_stack_status import get_stack_status
from docker_mcp_server.tools.inspect_drift import inspect_drift
from docker_mcp_server.tools.list_stacks import list_stacks
from docker_mcp_server.tools.plan_stack import plan_stack
from docker_mcp_server.tools.pull_image import pull_image
from docker_mcp_server.tools.remediate_drift import remediate_drift
from docker_mcp_server.tools.remove_container import remove_container
from docker_mcp_server.tools.resolve_dependency import resolve_dependency
from docker_mcp_server.tools.stop_stack import stop_stack
from docker_mcp_server.tools.validate_spec import validate_spec

_PREFLIGHT_TOOLS: list[Any] = [
    validate_spec,
    resolve_dependency,
]


def get_agent_tools() -> list[Any]:
    return _PREFLIGHT_TOOLS + [
        plan_stack,
        destroy_stack,
        destroy_all_stacks,
        stop_stack,
        remove_container,
        list_stacks,
        inspect_drift,
        remediate_drift,
        get_stack_status,
        get_logs,
        get_health,
        exec_docker,
    ]


def get_all_tools() -> list[Any]:
    from docker_mcp_server.tools.apply_stack import apply_stack

    return get_agent_tools() + [pull_image, apply_stack]


__all__ = ["get_agent_tools", "get_all_tools"]


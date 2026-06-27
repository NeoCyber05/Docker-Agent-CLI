"""Tool registry implementation (sibling to the ``tools/`` package).

Parity: ``src/tools.ts``.
"""

from __future__ import annotations

from typing import Any

from docker_agent.tools.check_port_conflict import check_port_conflict
from docker_agent.tools.destroy_all_stacks import destroy_all_stacks
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.tools.exec_docker import exec_docker
from docker_agent.tools.get_health import get_health
from docker_agent.tools.get_logs import get_logs
from docker_agent.tools.get_stack_status import get_stack_status
from docker_agent.tools.inspect_drift import inspect_drift
from docker_agent.tools.list_stacks import list_stacks
from docker_agent.tools.plan_stack import plan_stack
from docker_agent.tools.pull_image import pull_image
from docker_agent.tools.remove_container import remove_container
from docker_agent.tools.remediate_drift import remediate_drift
from docker_agent.tools.resolve_dependency import resolve_dependency
from docker_agent.tools.validate_spec import validate_spec

_PREFLIGHT_TOOLS: list[Any] = [
    validate_spec,
    resolve_dependency,
    check_port_conflict,
]


def get_agent_tools() -> list[Any]:
    return _PREFLIGHT_TOOLS + [
        plan_stack,
        destroy_stack,
        destroy_all_stacks,
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
    from docker_agent.tools.apply_stack import apply_stack

    return get_agent_tools() + [pull_image, apply_stack]


__all__ = ["get_agent_tools", "get_all_tools"]

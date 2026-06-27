"""Tool registry implementation (sibling to the ``tools/`` package).

Parity: ``src/tools.ts``.
"""

from __future__ import annotations

from typing import Any

from src.tools.check_port_conflict import check_port_conflict
from src.tools.destroy_all_stacks import destroy_all_stacks
from src.tools.destroy_stack import destroy_stack
from src.tools.exec_docker import exec_docker
from src.tools.get_health import get_health
from src.tools.get_logs import get_logs
from src.tools.get_stack_status import get_stack_status
from src.tools.inspect_drift import inspect_drift
from src.tools.list_stacks import list_stacks
from src.tools.plan_stack import plan_stack
from src.tools.pull_image import pull_image
from src.tools.remediate_drift import remediate_drift
from src.tools.resolve_dependency import resolve_dependency
from src.tools.validate_spec import validate_spec

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
        list_stacks,
        inspect_drift,
        remediate_drift,
        get_stack_status,
        get_logs,
        get_health,
        pull_image,
        exec_docker,
    ]


def get_all_tools() -> list[Any]:
    from src.tools.apply_stack import apply_stack

    return get_agent_tools() + [apply_stack]


__all__ = ["get_agent_tools", "get_all_tools"]
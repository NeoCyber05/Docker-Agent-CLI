"""Docker-agent tools package.

Registry helpers are loaded lazily so importing individual tool modules does
not pull in every tool implementation.
"""

from __future__ import annotations

from typing import Any


def get_agent_tools() -> list[Any]:
    from docker_mcp_server.tools import _registry

    return _registry.get_agent_tools()


def get_all_tools() -> list[Any]:
    from docker_mcp_server.tools import _registry

    return _registry.get_all_tools()


__all__ = ["get_agent_tools", "get_all_tools"]

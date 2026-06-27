"""Tool registry entrypoint (re-exports lazy registry)."""

from docker_agent.tools._registry import get_agent_tools, get_all_tools

__all__ = ["get_agent_tools", "get_all_tools"]
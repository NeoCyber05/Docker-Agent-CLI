"""Load LangChain tools from configured MCP servers."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from docker_agent.mcp.config import is_mcp_enabled, mcp_servers_for_langchain

_mcp_tools_cache: list[Any] | None = None


def reset_mcp_tools_cache() -> None:
    """Clear cached MCP tools (test helper)."""
    global _mcp_tools_cache
    _mcp_tools_cache = None


def warmup_mcp_stdio_transport() -> None:
    """Pre-connect MCP stdio servers before a Windows TUI owns terminal streams."""
    if sys.platform != "win32" or not is_mcp_enabled():
        return

    try:
        asyncio.run(load_mcp_langchain_tools())
    except Exception as err:
        raise RuntimeError(
            "Failed to start the Docker MCP server on Windows. "
            "Ensure docker-mcp-server is installed and on PATH, or set "
            "DOCKER_AGENT_MCP=0 to use the legacy in-process tool path."
        ) from err


async def load_mcp_langchain_tools(*, force_reload: bool = False) -> list[Any]:
    global _mcp_tools_cache
    if _mcp_tools_cache is not None and not force_reload:
        return _mcp_tools_cache

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ModuleNotFoundError as err:  # pragma: no cover - exercised by env setup
        raise RuntimeError(
            "DOCKER_AGENT_MCP=1 requires langchain-mcp-adapters. "
            "Install the dev dependencies or disable the MCP feature flag."
        ) from err

    client = MultiServerMCPClient(mcp_servers_for_langchain())
    tools = await client.get_tools()
    _mcp_tools_cache = list(tools)
    return _mcp_tools_cache


__all__ = [
    "load_mcp_langchain_tools",
    "reset_mcp_tools_cache",
    "warmup_mcp_stdio_transport",
]
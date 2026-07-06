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
    is_mcp_enabled()
    if sys.platform != "win32":
        return

    try:
        asyncio.run(load_mcp_langchain_tools())
    except Exception as err:
        raise RuntimeError(
            "Failed to start configured MCP server(s) on Windows. "
            "Ensure plugin servers are installed and on PATH, or set "
            "DOCKER_AGENT_MCP_CONFIG to a valid MCP config file."
        ) from err


async def load_mcp_langchain_tools(*, force_reload: bool = False) -> list[Any]:
    global _mcp_tools_cache
    is_mcp_enabled()
    if _mcp_tools_cache is not None and not force_reload:
        return _mcp_tools_cache

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ModuleNotFoundError as err:  # pragma: no cover - exercised by env setup
        raise RuntimeError(
            "MCP support requires langchain-mcp-adapters. "
            "Install the project dependencies; the legacy MCP-off path has been removed."
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

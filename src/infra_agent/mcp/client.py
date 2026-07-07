"""Load LangChain tools from configured MCP servers."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from infra_agent.mcp.capabilities import (
    load_mcp_capabilities,
    mcp_context_summary,
    mcp_list_resources,
)
from infra_agent.mcp.config import is_mcp_enabled, mcp_servers_for_langchain

_mcp_tools_cache: list[Any] | None = None
_mcp_runtime_preload: dict[str, dict[str, Any]] = {}
_active_plugin_selection: list[str] | None = None


def reset_mcp_tools_cache() -> None:
    """Clear cached MCP tools and plugin selection (test helper)."""
    global _mcp_tools_cache, _active_plugin_selection
    _mcp_tools_cache = None
    _active_plugin_selection = None
    _mcp_runtime_preload.clear()


def set_active_plugin_selection(names: list[str] | None) -> None:
    """Restrict which configured MCP servers get connected this session.

    ``None`` connects every configured server. Setting a selection invalidates any
    cached tools/runtime so the next load reflects the chosen plugins.
    """
    global _active_plugin_selection, _mcp_tools_cache
    _active_plugin_selection = list(names) if names is not None else None
    _mcp_tools_cache = None
    _mcp_runtime_preload.clear()


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

    client = MultiServerMCPClient(
        mcp_servers_for_langchain(selected=_active_plugin_selection)
    )
    tools = await client.get_tools()
    _mcp_tools_cache = list(tools)
    return _mcp_tools_cache


async def preload_mcp_runtime(cwd: str) -> None:
    """Preload MCP capabilities/context/resources for first-turn latency."""
    tools = await load_mcp_langchain_tools()
    capabilities = await load_mcp_capabilities(tools)
    context_summary = await mcp_context_summary(
        tools,
        capabilities=capabilities,
        cwd=cwd,
        fallback="",
    )
    resources = await mcp_list_resources(
        tools,
        capabilities=capabilities,
        cwd=cwd,
    )
    _mcp_runtime_preload[cwd] = {
        "capabilities": capabilities,
        "context_summary": context_summary,
        "resources": resources,
    }


def consume_preloaded_mcp_runtime(cwd: str) -> dict[str, Any] | None:
    """Return and remove preloaded runtime payload for cwd."""
    return _mcp_runtime_preload.pop(cwd, None)


__all__ = [
    "consume_preloaded_mcp_runtime",
    "load_mcp_langchain_tools",
    "preload_mcp_runtime",
    "reset_mcp_tools_cache",
    "set_active_plugin_selection",
    "warmup_mcp_stdio_transport",
]

"""Tests for MCP tool loading helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from infra_agent.mcp import client as mcp_client


@pytest.mark.asyncio
async def test_load_mcp_langchain_tools_uses_cache() -> None:
    mcp_client.reset_mcp_tools_cache()
    fake_tools = [object()]
    with patch(
        "langchain_mcp_adapters.client.MultiServerMCPClient",
        autospec=True,
    ) as client_cls:
        client_cls.return_value.get_tools = AsyncMock(return_value=fake_tools)
        first = await mcp_client.load_mcp_langchain_tools()
        second = await mcp_client.load_mcp_langchain_tools()
    assert first is second
    client_cls.assert_called_once()


def test_warmup_mcp_stdio_transport_skips_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_client.sys, "platform", "linux")
    with (
        patch.object(mcp_client, "is_mcp_enabled", return_value=True) as enabled,
        patch.object(mcp_client.asyncio, "run") as run,
    ):
        mcp_client.warmup_mcp_stdio_transport()
    enabled.assert_called_once()
    run.assert_not_called()


def test_warmup_mcp_stdio_transport_fails_when_mcp_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")
    with (
        patch.object(
            mcp_client,
            "is_mcp_enabled",
            side_effect=RuntimeError("legacy MCP-off path has been removed"),
        ),
        patch.object(mcp_client.asyncio, "run") as run,
        pytest.raises(RuntimeError, match="legacy MCP-off path has been removed"),
    ):
        mcp_client.warmup_mcp_stdio_transport()
    run.assert_not_called()

def test_warmup_mcp_stdio_transport_runs_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")
    with (
        patch.object(mcp_client, "is_mcp_enabled", return_value=True),
        patch.object(mcp_client.asyncio, "run") as run,
    ):
        mcp_client.warmup_mcp_stdio_transport()
        run.assert_called_once()
        coro = run.call_args.args[0]
        assert coro.__name__ == "load_mcp_langchain_tools"
        coro.close()


def test_warmup_mcp_stdio_transport_wraps_startup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")

    def _raise_bad_fd(coro: object) -> None:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        raise OSError(9, "Bad file descriptor")

    with (
        patch.object(mcp_client, "is_mcp_enabled", return_value=True),
        patch.object(mcp_client.asyncio, "run", side_effect=_raise_bad_fd),
        pytest.raises(RuntimeError, match="Failed to start configured MCP server"),
    ):
        mcp_client.warmup_mcp_stdio_transport()



@pytest.mark.asyncio
async def test_active_plugin_selection_filters_connected_servers() -> None:
    mcp_client.reset_mcp_tools_cache()
    captured: dict[str, object] = {}

    def _capture(servers: dict[str, object]) -> object:
        captured["servers"] = servers
        instance = AsyncMock()
        instance.get_tools = AsyncMock(return_value=[])
        return instance

    mcp_client.set_active_plugin_selection(["k8s"])
    with (
        patch.object(
            mcp_client,
            "mcp_servers_for_langchain",
            return_value={"k8s": {"command": "k8s-mcp-server"}},
        ) as servers_for,
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", side_effect=_capture),
    ):
        await mcp_client.load_mcp_langchain_tools(force_reload=True)

    servers_for.assert_called_once_with(selected=["k8s"])
    assert captured["servers"] == {"k8s": {"command": "k8s-mcp-server"}}
    mcp_client.reset_mcp_tools_cache()


def test_set_active_plugin_selection_invalidates_cache() -> None:
    mcp_client.reset_mcp_tools_cache()
    mcp_client._mcp_tools_cache = [object()]

    mcp_client.set_active_plugin_selection(["docker"])

    assert mcp_client._mcp_tools_cache is None
    mcp_client.reset_mcp_tools_cache()

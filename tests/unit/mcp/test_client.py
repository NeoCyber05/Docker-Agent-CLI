"""Tests for MCP tool loading helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from docker_agent.mcp import client as mcp_client


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
    enabled.assert_not_called()
    run.assert_not_called()


def test_warmup_mcp_stdio_transport_skips_when_mcp_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_client.sys, "platform", "win32")
    with (
        patch.object(mcp_client, "is_mcp_enabled", return_value=False),
        patch.object(mcp_client.asyncio, "run") as run,
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
        pytest.raises(RuntimeError, match="Failed to start the Docker MCP server"),
    ):
        mcp_client.warmup_mcp_stdio_transport()
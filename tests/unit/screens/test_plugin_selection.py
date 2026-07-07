"""Tests for the startup plugin selector."""

from __future__ import annotations

import pytest

from infra_agent.mcp.config import PluginDescriptor
from infra_agent.screens.plugin_selection import PluginSelectionApp, select_plugins


def _plugins() -> list[PluginDescriptor]:
    return [
        PluginDescriptor(name="docker", label="Docker", description="Compose stacks"),
        PluginDescriptor(name="k8s", label="Kubernetes", description="Clusters"),
    ]


@pytest.mark.asyncio
async def test_enter_confirms_preselected_plugins() -> None:
    app = PluginSelectionApp(_plugins(), {"docker", "k8s"})
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert set(app.return_value or []) == {"docker", "k8s"}


@pytest.mark.asyncio
async def test_space_toggles_highlighted_plugin_off() -> None:
    app = PluginSelectionApp(_plugins(), {"docker", "k8s"})
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")  # toggle the highlighted (first) plugin off
        await pilot.press("enter")
        await pilot.pause()
    assert set(app.return_value or []) == {"k8s"}


@pytest.mark.asyncio
async def test_toggle_all_then_connect_selects_everything() -> None:
    app = PluginSelectionApp(_plugins(), set())  # start with nothing ticked
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")  # toggle all -> select all
        await pilot.press("enter")
        await pilot.pause()
    assert set(app.return_value or []) == {"docker", "k8s"}


@pytest.mark.asyncio
async def test_cancel_returns_none() -> None:
    app = PluginSelectionApp(_plugins(), {"docker"})
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert app.return_value is None


def test_select_plugins_short_circuits_on_empty() -> None:
    assert select_plugins([]) == []

"""Tests for REPL Textual app."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from docker_agent.components.welcome_banner import WelcomeBanner
from docker_agent.query_engine import QueryEngine
from docker_agent.screens.repl import REPL
from docker_agent.services.api.types import CallModelParams, ProviderEvent
from docker_agent.state.state_store import StateStore
from docker_agent.types.events import PermissionRequest
from docker_agent.types.permissions import Approve
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine


def fake_provider(events: list[ProviderEvent | dict[str, Any]] | None = None):
    payload = events or []

    class _Provider:
        name = "fake"

        async def stream(self, _params: CallModelParams) -> AsyncIterator[ProviderEvent]:
            for event in payload:
                yield event  # type: ignore[misc]

    return _Provider()


def make_engine(tmp_project) -> QueryEngine:
    return QueryEngine(
        cwd=str(tmp_project),
        state_store=StateStore(str(tmp_project / ".docker-agent")),
        docker_engine=MockDockerEngine(),
        compose_runner=MockComposeRunner(str(tmp_project)),
        provider=fake_provider(),
        model="test-model",
    )


@pytest.mark.asyncio
async def test_repl_mounts_without_error(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#timeline") is not None


@pytest.mark.asyncio
async def test_welcome_banner_visible(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=True)
    async with app.run_test() as pilot:
        banner = pilot.app.query_one(WelcomeBanner)
        assert "docker-agent" in str(banner.render())


@pytest.mark.asyncio
async def test_slash_suggestions_visible(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test")
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/", "h", "e", "l", "p")
        await pilot.pause()
        suggestions = pilot.app.query_one("#suggestions")
        assert suggestions.display is True


@pytest.mark.asyncio
async def test_exit_slash_command_exits(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test")
    exited = False

    def mark_exit() -> None:
        nonlocal exited
        exited = True

    with patch.object(app, "exit", side_effect=mark_exit):
        async with app.run_test() as pilot:
            await pilot.click("#prompt-input")
            await pilot.press("/", "e", "x", "i", "t")
            await pilot.press("enter")
            await pilot.pause()
    assert exited is True


@pytest.mark.asyncio
async def test_permission_request_opens_dialog_and_responds(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test")
    app.session.pending_event = PermissionRequest(
        id="perm-1", tool="pull_image", input={"image": "nginx"}
    )
    app.session.interaction.phase = "awaiting_input"

    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.respond("perm-1", Approve())
        await pilot.pause()
        assert app.session.pending_event is None
        assert app.session.phase == "running"
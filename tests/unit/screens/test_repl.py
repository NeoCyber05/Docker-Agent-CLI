"""Tests for REPL Textual app."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from io import StringIO

from rich.console import Console

from docker_agent.components.activity_timeline import ActivityTimeline
from docker_agent.components.model_picker_dialog import ModelPickerDialog
from docker_agent.components.welcome_banner import WelcomeBanner
from docker_agent.services.model_catalog import CatalogRowHeader, CatalogRowModel
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
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#timeline") is not None


@pytest.mark.asyncio
async def test_welcome_banner_visible(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=True)
    async with app.run_test(size=(100, 30)) as pilot:
        banner = pilot.app.query_one(WelcomeBanner)
        buffer = StringIO()
        Console(file=buffer, width=100).print(banner.content)
        rendered = buffer.getvalue()
        assert "Docker Agent CLI" in rendered
        assert "##" in rendered
        assert "Tips for getting started" in rendered
        prompt = pilot.app.query_one("#prompt-input")
        assert prompt.region.y + prompt.region.height <= pilot.app.size.height


@pytest.mark.asyncio
async def test_slash_suggestions_visible(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/", "h", "e", "l", "p")
        await pilot.pause()
        suggestions = pilot.app.query_one("#suggestions")
        assert suggestions.display is True


@pytest.mark.asyncio
async def test_help_slash_command_renders_in_timeline(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/", "h", "e", "l", "p")
        await pilot.press("enter")
        await pilot.pause(delay=0.5)
        timeline = pilot.app.query_one("#timeline-content", ActivityTimeline)
        assert len(timeline.items) == 2
        assert "/help" in str(timeline.render())
        assert app._tick_task is not None
        assert not app._tick_task.done()


@pytest.mark.asyncio
async def test_exit_slash_command_exits(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
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
async def test_model_slash_command_mounts_inline_picker(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    rows = [
        CatalogRowHeader(provider="openai", connected=True),
        CatalogRowModel(provider="openai", model="gpt-4o"),
    ]

    async def fake_rows(_scope_provider: str | None = None) -> list[object]:
        return rows

    with patch.object(app, "_build_model_picker_rows", side_effect=fake_rows):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.click("#prompt-input")
            await pilot.press("/", "m", "o", "d", "e", "l")
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            picker = pilot.app.query_one("#model-picker", ModelPickerDialog)
            prompt_input = pilot.app.query_one("#prompt-input")
            assert picker is not None
            assert prompt_input.disabled is True
            assert pilot.app.focused is picker
            assert pilot.app.query_one("#timeline") is not None
            await pilot.press("escape")
            await pilot.pause(delay=0.2)
            assert prompt_input.disabled is False


@pytest.mark.asyncio
async def test_prompt_enabled_while_agent_running(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    app.session.interaction.phase = "running"

    async with app.run_test() as pilot:
        await pilot.pause(delay=0.3)
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.disabled is False
        assert "Agent thinking" in pilot.app.query_one("#phase-hint").content


@pytest.mark.asyncio
async def test_permission_request_opens_dialog_and_responds(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    app.session.pending_event = PermissionRequest(
        id="perm-1", tool="pull_image", input={"image": "nginx"}
    )
    app.session.interaction.phase = "awaiting_input"

    async with app.run_test() as pilot:
        await pilot.pause(delay=0.5)
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.disabled is True
        await pilot.press("y")
        await pilot.pause(delay=0.5)
        assert app.session.pending_event is None
        assert app.session.phase == "running"
        assert prompt_input.disabled is False
        assert not pilot.app.query("#permission-prompt")


@pytest.mark.asyncio
async def test_plan_ready_shows_in_timeline_and_accepts_approval(tmp_project) -> None:
    from docker_agent.types.events import PlanReady
    from docker_agent.types.stack import StackDiff

    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    app.session.pending_event = PlanReady(
        id="plan-1",
        compose_yaml="services:\n  web:\n    image: nginx",
        diff=StackDiff(stackName="demo", status="missing", serviceDiffs=[]),
    )
    app.session.dispatch_activity(
        {
            "type": "plan_ready",
            "request_id": "plan-1",
            "compose_yaml": "services:\n  web:\n    image: nginx",
            "diff": StackDiff(stackName="demo", status="missing", serviceDiffs=[]),
            "auto_generated_secrets": None,
            "config_files": None,
        }
    )
    app.session.interaction.phase = "awaiting_input"

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(delay=0.5)
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.disabled is True
        timeline = str(pilot.app.query_one("#timeline-content").render())
        assert "Plan preview" in timeline
        await pilot.press("y")
        await pilot.pause(delay=0.5)
        assert app.session.pending_event is None
        assert app.session.phase == "running"
        assert any(
            item.type == "plan" and item.status == "approved"
            for item in app.session.activity_state.items
        )
        timeline_after = str(pilot.app.query_one("#timeline-content").render())
        assert "Plan approved" in timeline_after


@pytest.mark.asyncio
async def test_policy_permission_always_allow_unblocks_prompt(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    app.session.pending_event = PermissionRequest(
        id="policy-1",
        tool="initialize_project_policy",
        input={
            "reason": "Project policy file (project-policies.yaml) is missing",
            "path": str(tmp_project / "project-policies.yaml"),
            "content": "project:\n  hardDeny: []\n  require: []\n",
        },
    )
    app.session.interaction.phase = "awaiting_input"

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(delay=0.5)
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.disabled is True
        await pilot.press("a")
        await pilot.pause(delay=0.5)
        assert app.session.pending_event is None
        app.session.interaction.phase = "idle"
        await pilot.pause(delay=0.2)
        assert prompt_input.disabled is False


@pytest.mark.asyncio
async def test_model_picker_selects_and_closes(tmp_project) -> None:
    app = REPL(engine=make_engine(tmp_project), version="0.1.0-test", show_banner=False)
    rows = [
        CatalogRowHeader(provider="openai", connected=True),
        CatalogRowModel(provider="openai", model="gpt-4o"),
    ]

    async def fake_rows(_scope_provider: str | None = None) -> list[object]:
        return rows

    with patch.object(app, "_build_model_picker_rows", side_effect=fake_rows):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.click("#prompt-input")
            await pilot.press("/", "m", "o", "d", "e", "l")
            await pilot.press("enter")
            await pilot.pause(delay=0.2)
            
            picker = pilot.app.query_one("#model-picker", ModelPickerDialog)
            assert picker is not None
            assert pilot.app.focused is picker

            await pilot.press("down")
            await pilot.pause(delay=0.1)
            await pilot.press("enter")
            await pilot.pause(delay=0.2)
            
            # The picker should now be closed and removed
            from textual.css.query import NoMatches
            with pytest.raises(NoMatches):
                pilot.app.query_one("#model-picker")
            
            # Model should be updated
            assert app.active_provider_name == "openai"
            assert app.active_model == "gpt-4o"
            
            # There should be a notification in the session timeline
            last_msg = app.session.activity_state.items[-1]
            assert last_msg.type == "text"
            assert last_msg.role == "assistant"
            assert "Model set to gpt-4o (openai)" in last_msg.text
from __future__ import annotations

from textual import events
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.widgets import Static

from docker_agent.ui.textual_compat import patch_selection_none_parent_crash


class _SelectableHost(App):
    def compose(self) -> ComposeResult:
        yield Static("selectable text for mouse selection", id="content")


async def test_forward_event_survives_orphan_widget_during_mousedown() -> None:
    patch_selection_none_parent_crash()
    app = _SelectableHost()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pilot.app.screen
        await pilot.pause()

        orphan = Static("orphan text")
        orphan._parent = None  # noqa: SLF001 â€” simulate DOM detach race

        region = pilot.app.query_one("#content", Static).region
        event = events.MouseDown(
            orphan,
            float(region.x + 1),
            float(region.y),
            0,
            0,
            1,
            False,
            False,
            False,
            screen_x=float(region.x + 1),
            screen_y=float(region.y),
        )

        def fake_get(_x: float, _y: float) -> tuple[Static, Offset]:
            return orphan, Offset(1, 0)

        screen.get_widget_and_offset_at = fake_get  # type: ignore[method-assign]
        screen._forward_event(event)
        assert screen._select_state is None


async def test_forward_event_still_starts_selection_for_valid_widget() -> None:
    patch_selection_none_parent_crash()
    app = _SelectableHost()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pilot.app.screen
        widget = pilot.app.query_one("#content", Static)
        await pilot.pause()

        region = widget.region
        event = events.MouseDown(
            widget,
            float(region.x + 1),
            float(region.y),
            0,
            0,
            1,
            False,
            False,
            False,
            screen_x=float(region.x + 1),
            screen_y=float(region.y),
        )
        screen._forward_event(event)
        assert screen._select_state is not None


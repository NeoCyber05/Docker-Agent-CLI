from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from src.components.queue_panel import QueuePanel


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_queue_panel_shows_items() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.push_screen(QueuePanel(queue=["first", "second"]))
        await pilot.pause()
        rendered = str(pilot.app.screen.query_one("#queue-list").content)
        assert "first" in rendered
        assert "second" in rendered


async def test_queue_panel_remove_action() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(QueuePanel(queue=["only"]), check)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert responses[0] is not None
        assert responses[0].kind == "remove"  # type: ignore[attr-defined]
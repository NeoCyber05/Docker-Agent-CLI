from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from infra_agent.components.log_pane import LogPane


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_log_pane_renders_lines() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.push_screen(
            LogPane(stack_name="demo", service="web", lines=["line-1", "line-2"])
        )
        await pilot.pause()
        log = pilot.app.screen.query_one("#log-output")
        assert len(log.lines) == 2
        rendered = "\n".join(str(line) for line in log.lines)
        assert "line-" in rendered


async def test_log_pane_close() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(LogPane(stack_name="demo", lines=[]), check)
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None

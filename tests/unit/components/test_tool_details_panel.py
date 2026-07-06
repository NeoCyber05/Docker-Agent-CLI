from __future__ import annotations

from textual.app import App, ComposeResult

from docker_agent.components.tool_details_panel import ToolDetailsPanel, render_tool_details
from docker_agent.ui.activity import ToolActivity


class DetailsApp(App):
    def compose(self) -> ComposeResult:
        yield ToolDetailsPanel(
            ToolActivity(
                id="t1",
                name="list_stacks",
                title="List stacks",
                summary="List all stacks",
                status="running",
                detail_lines=["line-1"],
                progress_msgs=["working"],
            )
        )


async def test_tool_details_panel_renders_activity() -> None:
    app = DetailsApp()
    async with app.run_test() as pilot:
        panel = pilot.app.query_one(ToolDetailsPanel)
        rendered = str(panel.content)
        assert "List stacks" in rendered
        assert "line-1" in rendered
        assert "working" in rendered


def test_tool_details_panel_empty_state() -> None:
    content = render_tool_details(None)
    assert "No tool selected" in str(content)

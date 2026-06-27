from __future__ import annotations

from textual.app import App, ComposeResult

from src.components.activity_timeline import ActivityTimeline, render_activity_timeline
from src.ui.activity import TextActivity, ToolActivity


class TimelineApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.items = [
            ToolActivity(
                id="t1",
                name="list_stacks",
                title="List stacks",
                summary="List all stacks",
                status="running",
                progress_msgs=["Listing..."],
            )
        ]

    def compose(self) -> ComposeResult:
        yield ActivityTimeline(items=self.items, active_tool_activity_id="t1")


async def test_activity_timeline_shows_running_tool() -> None:
    app = TimelineApp()
    async with app.run_test() as pilot:
        timeline = pilot.app.query_one(ActivityTimeline)
        assert "List stacks" in str(timeline.content)


def test_activity_timeline_renders_user_text() -> None:
    content = render_activity_timeline(
        [TextActivity(id="u1", role="user", text="hello")],
        active_tool_activity_id=None,
    )
    assert "hello" in str(content)
from __future__ import annotations

from textual.app import App, ComposeResult

from docker_agent.components.activity_timeline import ActivityTimeline, render_activity_timeline
from docker_agent.ui.activity import TextActivity, ToolActivity


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


def test_activity_timeline_renders_plan() -> None:
    from docker_agent.types.stack import StackDiff
    from docker_agent.ui.activity import PlanActivity

    diff = StackDiff(stackName="demo", status="missing", serviceDiffs=[])
    content = render_activity_timeline(
        [
            PlanActivity(
                id="plan-1",
                request_id="req-1",
                compose_yaml="services:\n  web:\n    image: nginx",
                diff=diff,
                status="approved",
            )
        ]
    )
    assert "Plan preview" in str(content)
    assert "Plan approved" in str(content)


def test_activity_timeline_renders_user_text() -> None:
    content = render_activity_timeline(
        [TextActivity(id="u1", role="user", text="hello")],
        active_tool_activity_id=None,
    )
    assert "hello" in str(content)


def test_activity_timeline_renders_assistant_bold_without_markers() -> None:
    content = render_activity_timeline(
        [TextActivity(id="a1", role="assistant", text="Use **PostgreSQL** for storage")],
        active_tool_activity_id=None,
    )
    text = str(content)
    assert "PostgreSQL" in text
    assert "**" not in text
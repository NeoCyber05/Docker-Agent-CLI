from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from src.components.plan_preview import PlanPreview
from src.types.stack import FieldChange, ServiceDiff, ServiceSnapshot, StackDiff


def _sample_diff() -> StackDiff:
    return StackDiff(
        stackName="demo",
        status="drift",
        serviceDiffs=[
            ServiceDiff(
                service="web",
                desired=ServiceSnapshot(
                    image="nginx:latest",
                    ports=["80:80"],
                    env={"visible": {}, "secretKeys": [], "secretHashesByKey": {}},
                    volumes=[],
                    replicaCount=1,
                ),
                actual=None,
                changes=[FieldChange(field="image", **{"from": None, "to": "nginx:latest"})],
            )
        ],
    )


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_plan_preview_approve() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object] = []

        def check(response: object) -> None:
            responses.append(response)

        pilot.app.push_screen(
            PlanPreview(compose_yaml="services:\n  web:\n    image: nginx", diff=_sample_diff()),
            check,
        )
        await pilot.pause()
        rendered = str(pilot.app.screen.query_one("#service-diffs").content)
        assert "web" in rendered
        await pilot.press("y")
        await pilot.pause()
        assert responses[0].kind == "approve"  # type: ignore[attr-defined]
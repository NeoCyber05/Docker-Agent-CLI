from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.permission_dialog import PermissionDialog


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_permission_dialog_approve() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object] = []

        def check(response: object) -> None:
            responses.append(response)

        pilot.app.push_screen(PermissionDialog(tool="pull_image", input={"image": "nginx"}), check)
        await pilot.press("y")
        await pilot.pause()
        assert len(responses) == 1
        assert responses[0].kind == "approve"  # type: ignore[attr-defined]


async def test_permission_dialog_deny() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object] = []

        def check(response: object) -> None:
            responses.append(response)

        pilot.app.push_screen(PermissionDialog(tool="pull_image"), check)
        await pilot.press("n")
        await pilot.pause()
        assert responses[0].kind == "deny"  # type: ignore[attr-defined]
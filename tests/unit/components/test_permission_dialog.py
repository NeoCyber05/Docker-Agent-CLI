from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.permission_dialog import PermissionAnswered, PermissionDialog


class Host(App):
    DEFAULT_CSS = """
    #timeline { height: 1fr; }
    PermissionDialog { height: auto; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.responses: list[object] = []

    def compose(self) -> ComposeResult:
        yield Static("timeline", id="timeline")
        yield Static("prompt", id="prompt")

    def on_permission_answered(self, message: PermissionAnswered) -> None:
        self.responses.append(message.response)


async def test_permission_dialog_approve() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            PermissionDialog(tool="pull_image", input={"image": "nginx"}, id="permission-prompt"),
            after="#timeline",
        )
        await pilot.press("y")
        await pilot.pause()
        assert len(app.responses) == 1
        assert app.responses[0].kind == "approve"  # type: ignore[attr-defined]


async def test_permission_dialog_always_allow() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            PermissionDialog(
                tool="initialize_project_policy",
                input_data={
                    "reason": "Project policy file is missing",
                    "path": "project-policies.yaml",
                    "content": "project:\n  hardDeny: []\n",
                },
                id="permission-prompt",
            ),
            after="#timeline",
        )
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert app.responses[0].kind == "always_allow_in_session"  # type: ignore[attr-defined]


async def test_permission_dialog_deny() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            PermissionDialog(tool="pull_image", id="permission-prompt"),
            after="#timeline",
        )
        await pilot.press("n")
        await pilot.pause()
        assert app.responses[0].kind == "deny"  # type: ignore[attr-defined]

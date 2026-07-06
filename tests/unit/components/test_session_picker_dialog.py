from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.session_picker_dialog import (
    SessionChoice,
    SessionPickerClosed,
    SessionPickerDialog,
)


class Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.responses: list[SessionChoice | None] = []

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")
        yield Static("prompt", id="prompt")

    def on_session_picker_closed(self, message: SessionPickerClosed) -> None:
        self.responses.append(message.result)


async def test_session_picker_dialog_selects_session() -> None:
    app = Host()
    async with app.run_test() as pilot:
        entries = [
            {
                "id": "sess-a",
                "created_at": "t",
                "updated_at": "2026-06-27T10:00:00Z",
                "first_prompt": "deploy nginx",
                "stack_names": ["web"],
            }
        ]
        pilot.app.mount(SessionPickerDialog(entries=entries), after="#prompt")
        await pilot.pause()
        await pilot.click("#session-picker-dialog")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.responses[0], SessionChoice)
        assert app.responses[0].session_id == "sess-a"


async def test_session_picker_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        entries = [
            {
                "id": "sess-a",
                "created_at": "t",
                "updated_at": "2026-06-27T10:00:00Z",
                "first_prompt": "deploy nginx",
                "stack_names": [],
            }
        ]
        pilot.app.mount(SessionPickerDialog(entries=entries), after="#prompt")
        await pilot.pause()
        await pilot.click("#session-picker-dialog")
        await pilot.press("escape")
        await pilot.pause()
        assert app.responses[0] is None

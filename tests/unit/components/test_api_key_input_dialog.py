from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.api_key_input_dialog import ApiKeyInputClosed, ApiKeyInputDialog


class Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.responses: list[object | None] = []

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")
        yield Static("prompt", id="prompt")

    def on_api_key_input_closed(self, message: ApiKeyInputClosed) -> None:
        self.responses.append(message.result)


async def test_api_key_input_dialog_returns_value() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            ApiKeyInputDialog(provider="openai", env_var_name="OPENAI_API_KEY"),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#api-key-input")
        await pilot.press("k", "e", "y", "-", "1", "2", "3")
        await pilot.press("enter")
        await pilot.pause()
        assert app.responses[0] == "key-123"


async def test_api_key_input_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            ApiKeyInputDialog(provider="openai", env_var_name="OPENAI_API_KEY"),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#api-key-input")
        await pilot.press("escape")
        await pilot.pause()
        assert app.responses[0] is None

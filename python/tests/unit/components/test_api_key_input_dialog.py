from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.api_key_input_dialog import ApiKeyInputDialog


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_api_key_input_dialog_returns_value() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(
            ApiKeyInputDialog(provider="openai", env_var_name="OPENAI_API_KEY"),
            check,
        )
        await pilot.pause()
        await pilot.click("#api-key-input")
        await pilot.press("k", "e", "y", "-", "1", "2", "3")
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0] == "key-123"


async def test_api_key_input_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(
            ApiKeyInputDialog(provider="openai", env_var_name="OPENAI_API_KEY"),
            check,
        )
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None
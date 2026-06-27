from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.ollama_setup_dialog import OllamaSetupDialog


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_ollama_setup_dialog_retry() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(OllamaSetupDialog(host="http://localhost:11434"), check)
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0] is not None
        assert responses[0].action == "retry"  # type: ignore[attr-defined]


async def test_ollama_setup_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(OllamaSetupDialog(host="http://localhost:11434"), check)
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None
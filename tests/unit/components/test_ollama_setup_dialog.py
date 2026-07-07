from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from infra_agent.components.ollama_setup_dialog import (
    OllamaSetupClosed,
    OllamaSetupDialog,
)


class Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.responses: list[object | None] = []

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")
        yield Static("prompt", id="prompt")

    def on_ollama_setup_closed(self, message: OllamaSetupClosed) -> None:
        self.responses.append(message.result)


async def test_ollama_setup_dialog_retry() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            OllamaSetupDialog(host="http://localhost:11434"),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#host-input")
        await pilot.press("enter")
        await pilot.pause()
        assert app.responses[0] is not None
        assert app.responses[0].action == "retry"  # type: ignore[attr-defined]


async def test_ollama_setup_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            OllamaSetupDialog(host="http://localhost:11434"),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#host-input")
        await pilot.press("escape")
        await pilot.pause()
        assert app.responses[0] is None


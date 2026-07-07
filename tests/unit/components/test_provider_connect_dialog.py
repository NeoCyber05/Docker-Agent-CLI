from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from infra_agent.components.provider_connect_dialog import (
    ProviderConnectClosed,
    ProviderConnectDialog,
)
from infra_agent.services.provider_status import ProviderStatus


class Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.responses: list[object | None] = []

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")
        yield Static("prompt", id="prompt")

    def on_provider_connect_closed(self, message: ProviderConnectClosed) -> None:
        self.responses.append(message.result)


async def test_provider_connect_dialog_selects_provider() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            ProviderConnectDialog(
                statuses=[
                    ProviderStatus(provider="gemini", connected=True),
                    ProviderStatus(provider="openai", connected=False),
                    ProviderStatus(provider="openrouter", connected=False),
                    ProviderStatus(provider="ollama", connected=False),
                ]
            ),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#provider-connect-dialog")
        await pilot.press("enter")
        await pilot.pause()
        assert app.responses[0] == "gemini"


async def test_provider_connect_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        pilot.app.mount(
            ProviderConnectDialog(
                statuses=[ProviderStatus(provider="gemini", connected=True)]
            ),
            after="#prompt",
        )
        await pilot.pause()
        await pilot.click("#provider-connect-dialog")
        await pilot.press("escape")
        await pilot.pause()
        assert app.responses[0] is None


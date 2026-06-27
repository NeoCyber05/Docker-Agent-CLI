from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.provider_connect_dialog import ProviderConnectDialog, ProviderStatus


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_provider_connect_dialog_selects_provider() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(
            ProviderConnectDialog(
                statuses=[
                    ProviderStatus(provider="gemini", connected=True),
                    ProviderStatus(provider="openai", connected=False),
                    ProviderStatus(provider="openrouter", connected=False),
                    ProviderStatus(provider="ollama", connected=False),
                ]
            ),
            check,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0] == "gemini"


async def test_provider_connect_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(
            ProviderConnectDialog(statuses=[ProviderStatus(provider="gemini", connected=True)]),
            check,
        )
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None
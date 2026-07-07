from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from infra_agent.components.secrets_input_dialog import SecretsInputDialog


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_secrets_input_dialog_collects_values() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object] = []

        def check(response: object) -> None:
            responses.append(response)

        pilot.app.push_screen(
            SecretsInputDialog(service="web", keys=["API_KEY"], reason="Required"),
            check,
        )
        await pilot.pause()
        await pilot.click("#secret-input")
        await pilot.press("s", "e", "c", "r", "e", "t")
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0].kind == "secrets_input_values"  # type: ignore[attr-defined]
        assert responses[0].values == {"API_KEY": "secret"}  # type: ignore[attr-defined]

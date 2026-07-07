from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from infra_agent.components.typed_confirm_dialog import TypedConfirmDialog


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_typed_confirm_dialog_accepts_matching_phrase() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object] = []

        def check(response: object) -> None:
            responses.append(response)

        pilot.app.push_screen(
            TypedConfirmDialog(phrase="DESTROY ALL", reason="Dangerous action"),
            check,
        )
        await pilot.pause()
        await pilot.click("#phrase-input")
        await pilot.press("D", "E", "S", "T", "R", "O", "Y", " ", "A", "L", "L")
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0].kind == "typed_confirm_value"  # type: ignore[attr-defined]

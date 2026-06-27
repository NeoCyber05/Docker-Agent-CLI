from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from src.commands.registry import Command
from src.components.command_palette import CommandPalette


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_command_palette_selects_command() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        commands = [
            Command(id="help", title="Help", description="Show help", shortcut="F1"),
            Command(id="clear", title="Clear", description="Clear chat"),
        ]
        pilot.app.push_screen(CommandPalette(commands=commands), check)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert responses[0] is not None
        assert responses[0].id == "help"  # type: ignore[attr-defined]


async def test_command_palette_close() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        pilot.app.push_screen(
            CommandPalette(commands=[Command(id="help", title="Help", description="Show help")]),
            check,
        )
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None
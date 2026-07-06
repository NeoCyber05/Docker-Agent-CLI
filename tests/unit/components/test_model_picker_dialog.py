from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.model_picker_dialog import (
    ModelChoice,
    ModelPickerClosed,
    ModelPickerDialog,
)
from docker_agent.services.model_catalog import CatalogRowHeader, CatalogRowModel


class Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.responses: list[object | None] = []

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")
        yield Static("prompt", id="prompt")

    def on_model_picker_closed(self, message: ModelPickerClosed) -> None:
        self.responses.append(message.result)


async def test_model_picker_dialog_selects_model() -> None:
    app = Host()
    async with app.run_test() as pilot:
        rows = [
            CatalogRowHeader(provider="openai", connected=True),
            CatalogRowModel(provider="openai", model="gpt-4o"),
        ]
        pilot.app.mount(ModelPickerDialog(rows=rows), after="#prompt")
        await pilot.pause()
        await pilot.click("#model-picker-dialog")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.responses[0], ModelChoice)
        assert app.responses[0].provider == "openai"
        assert app.responses[0].model == "gpt-4o"


async def test_model_picker_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        rows = [
            CatalogRowHeader(provider="openai", connected=True),
            CatalogRowModel(provider="openai", model="gpt-4o"),
        ]
        pilot.app.mount(ModelPickerDialog(rows=rows), after="#prompt")
        await pilot.pause()
        await pilot.click("#model-picker-dialog")
        await pilot.press("escape")
        await pilot.pause()
        assert app.responses[0] is None

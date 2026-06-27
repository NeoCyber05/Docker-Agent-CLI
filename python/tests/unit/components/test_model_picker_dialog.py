from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from docker_agent.components.model_picker_dialog import ModelChoice, ModelPickerDialog
from docker_agent.services.model_catalog import CatalogRowHeader, CatalogRowModel


class Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_model_picker_dialog_selects_model() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        rows = [
            CatalogRowHeader(provider="openai", connected=True),
            CatalogRowModel(provider="openai", model="gpt-4o"),
        ]
        pilot.app.push_screen(ModelPickerDialog(rows=rows), check)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(responses[0], ModelChoice)
        assert responses[0].provider == "openai"
        assert responses[0].model == "gpt-4o"


async def test_model_picker_dialog_cancel() -> None:
    app = Host()
    async with app.run_test() as pilot:
        responses: list[object | None] = []

        def check(response: object | None) -> None:
            responses.append(response)

        rows = [
            CatalogRowHeader(provider="openai", connected=True),
            CatalogRowModel(provider="openai", model="gpt-4o"),
        ]
        pilot.app.push_screen(ModelPickerDialog(rows=rows), check)
        await pilot.press("escape")
        await pilot.pause()
        assert responses[0] is None
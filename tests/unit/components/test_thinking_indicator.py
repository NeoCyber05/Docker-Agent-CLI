from __future__ import annotations

from textual.app import App, ComposeResult

from docker_agent.components.thinking_indicator import ThinkingIndicator


class ThinkingApp(App):
    def compose(self) -> ComposeResult:
        yield ThinkingIndicator()


class CustomLabelApp(App):
    def compose(self) -> ComposeResult:
        yield ThinkingIndicator(label="Apply stack: web")


async def test_thinking_indicator_shows_spinner_text() -> None:
    app = ThinkingApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(ThinkingIndicator)
        rendered = str(indicator.content)
        assert "Thinking" in rendered
        assert "s" in rendered


async def test_thinking_indicator_custom_label() -> None:
    app = CustomLabelApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(ThinkingIndicator)
        rendered = str(indicator.content)
        assert "Apply stack: web" in rendered
        assert "Thinking" not in rendered


async def test_thinking_indicator_label_updates() -> None:
    app = ThinkingApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(ThinkingIndicator)
        indicator.label = "Apply stack: demo"
        rendered = str(indicator.content)
        assert "Apply stack: demo" in rendered

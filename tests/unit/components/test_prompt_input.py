from __future__ import annotations

from textual.app import App, ComposeResult

from docker_agent.components.prompt_input import PromptInput, PromptSubmitted


class PromptApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInput()

    def on_prompt_submitted(self, message: PromptSubmitted) -> None:
        self.submitted.append(message.text)


async def test_prompt_input_shows_slash_suggestions() -> None:
    app = PromptApp()
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/")
        await pilot.press("h")
        await pilot.pause()
        suggestions = pilot.app.query_one("#suggestions")
        assert suggestions.display is True


async def test_prompt_input_tab_completes_suggestion() -> None:
    app = PromptApp()
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/")
        await pilot.press("h")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.value.startswith("/help")
        assert prompt_input.cursor_position == len(prompt_input.value)


async def test_prompt_input_enter_completes_suggestion_cursor_at_end() -> None:
    app = PromptApp()
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("/")
        await pilot.press("h")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.value.startswith("/help")
        assert prompt_input.cursor_position == len(prompt_input.value)
        assert app.submitted == []


async def test_prompt_input_submits_trimmed_text() -> None:
    app = PromptApp()
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == ["hello"]


async def test_prompt_input_history_navigation() -> None:
    app = PromptApp()
    async with app.run_test() as pilot:
        await pilot.click("#prompt-input")
        await pilot.press("f", "i", "r", "s", "t")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#prompt-input")
        await pilot.press("s", "e", "c", "o", "n", "d")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#prompt-input")
        await pilot.press("up")
        await pilot.pause()
        prompt_input = pilot.app.query_one("#prompt-input")
        assert prompt_input.value == "second"
        await pilot.press("up")
        await pilot.pause()
        assert prompt_input.value == "first"

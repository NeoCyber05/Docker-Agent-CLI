"""Prompt input with slash command suggestions."""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, ListItem, ListView, Static

from docker_agent.components.slash_highlighter import SlashCommandHighlighter
from docker_agent.slash_commands import get_slash_command_suggestions
from docker_agent.slash_router import SlashCommandDef
from docker_agent.ui.interaction_state import InteractionPhase

PHASE_HINTS: dict[InteractionPhase, str] = {
    "running": "(Agent thinking — type to queue a follow-up, Ctrl+C to cancel)",
    "cancelling": "(Cancelling… Ctrl+C to force-stop)",
    "awaiting_input": "(Awaiting your response…)",
    "queue_paused": "(Queue paused — Enter to resume, Ctrl+Q to manage)",
    "idle": "(Alt+Enter newline, ↑↓ history, Ctrl+O tool details)",
}


class PromptSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ResumeQueue(Message):
    pass


class PromptInput(Vertical):
    phase: reactive[InteractionPhase] = reactive("idle")
    prefill: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_idx = -1
        self._draft = ""
        self._suggestion_idx = 0

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Enter prompt…",
            id="prompt-input",
            highlighter=SlashCommandHighlighter(),
        )
        yield Static(PHASE_HINTS["idle"], id="phase-hint", classes="dim")
        yield ListView(id="suggestions")

    def on_mount(self) -> None:
        self.query_one("#suggestions", ListView).display = False
        self.query_one("#prompt-input", Input).focus()

    def watch_phase(self, phase: InteractionPhase) -> None:
        self.query_one("#phase-hint", Static).update(PHASE_HINTS.get(phase, ""))

    def _input_widget(self) -> Input:
        return self.query_one("#prompt-input", Input)

    def _move_cursor_to_end(self) -> None:
        widget = self._input_widget()
        widget.cursor_position = len(widget.value)

    def watch_prefill(self, value: str | None) -> None:
        if value is None:
            return
        widget = self._input_widget()
        widget.value = value
        self._move_cursor_to_end()
        self._suggestion_idx = 0
        self._update_suggestions()

    def _current_text(self) -> str:
        return self._input_widget().value

    def _set_text(self, text: str) -> None:
        widget = self._input_widget()
        widget.value = text
        self._move_cursor_to_end()
        self._update_suggestions()

    def _suggestions(self) -> list[SlashCommandDef]:
        return get_slash_command_suggestions(self._current_text())

    def _update_suggestions(self) -> None:
        suggestions = self._suggestions()
        list_view = self.query_one("#suggestions", ListView)
        list_view.clear()
        if suggestions:
            for suggestion in suggestions:
                list_view.append(
                    ListItem(Static(f"{suggestion.usage} - {suggestion.description}"))
                )
            list_view.display = True
            self._suggestion_idx = min(self._suggestion_idx, len(suggestions) - 1)
            if list_view.children:
                list_view.index = self._suggestion_idx
        else:
            list_view.display = False
            self._suggestion_idx = 0

    def _accept_suggestion(self) -> bool:
        suggestions = self._suggestions()
        if not suggestions:
            return False
        idx = min(self._suggestion_idx, len(suggestions) - 1)
        suggestion = suggestions[idx]
        current = self._current_text().strip().lower()
        if current == suggestion.insert_text.strip().lower():
            return False
        self._set_text(suggestion.insert_text)
        self._input_widget().focus()
        self._history_idx = -1
        self._draft = ""
        return True

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt-input":
            self._suggestion_idx = 0
            self._update_suggestions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt-input":
            return
        if self._accept_suggestion():
            return
        text = event.input.value.strip()
        if text:
            self._history.append(event.input.value)
            self._history_idx = -1
            self._draft = ""
            self.post_message(PromptSubmitted(text))
        elif self.phase == "queue_paused":
            self.post_message(ResumeQueue())
        event.input.value = ""
        self._update_suggestions()

    def on_key(self, event: events.Key) -> None:
        suggestions = self._suggestions()
        if event.key == "tab" and suggestions:
            if self._accept_suggestion():
                event.prevent_default()
                event.stop()
            return

        if event.key == "up":
            if suggestions:
                self._suggestion_idx = (
                    len(suggestions) - 1 if self._suggestion_idx <= 0 else self._suggestion_idx - 1
                )
                self.query_one("#suggestions", ListView).index = self._suggestion_idx
                event.prevent_default()
                event.stop()
                return
            if not self._history:
                return
            if self._history_idx == -1:
                self._draft = self._current_text()
                self._history_idx = len(self._history) - 1
            elif self._history_idx > 0:
                self._history_idx -= 1
            else:
                return
            self._set_text(self._history[self._history_idx])
            event.prevent_default()
            event.stop()
            return

        if event.key == "down":
            if suggestions:
                self._suggestion_idx = (self._suggestion_idx + 1) % len(suggestions)
                self.query_one("#suggestions", ListView).index = self._suggestion_idx
                event.prevent_default()
                event.stop()
                return
            if self._history_idx == -1:
                return
            next_idx = self._history_idx + 1
            if next_idx >= len(self._history):
                self._history_idx = -1
                self._set_text(self._draft)
            else:
                self._history_idx = next_idx
                self._set_text(self._history[self._history_idx])
            event.prevent_default()
            event.stop()
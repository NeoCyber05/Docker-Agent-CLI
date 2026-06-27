"""Spinning thinking indicator."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.widgets import Static

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ThinkingIndicator(Static):
    """Static widget showing a spinner while the agent is thinking."""

    def __init__(self, *, running: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._running = running
        self._frame_index = 0
        self._started_at = time.time()
        self._update_display()

    def on_mount(self) -> None:
        if self._running:
            self.set_interval(0.1, self._tick_spinner)
            self.set_interval(1.0, self._tick_elapsed)

    def _tick_spinner(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(SPINNER_FRAMES)
        self._update_display()

    def _tick_elapsed(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        frame = SPINNER_FRAMES[self._frame_index]
        elapsed = int(time.time() - self._started_at)
        self.update(Text(f"{frame} Thinking… {elapsed}s", style="green"))
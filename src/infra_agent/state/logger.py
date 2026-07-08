"""Structured NDJSON logger with secret redaction.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from infra_agent.state.secret_redactor import redact_text, redact_value_deep

LogLevel = Literal["debug", "info", "warn", "error"]


class LogEntry(BaseModel):
    """One log row. ``message`` and ``data`` are redacted by the logger."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    ts: str
    level: LogLevel
    session_id: str = Field(alias="sessionId")
    iteration: int | None = None
    category: str
    message: str
    data: dict[str, Any] | None = None


class StructuredLogger:
    """Buffered, best-effort NDJSON logger per session."""

    def __init__(self, log_dir: str | os.PathLike[str], session_id: str) -> None:
        self._log_path = Path(log_dir) / f"{session_id}.ndjson"
        self._buffer: list[str] = []
        self._max_buffer = 50
        self._flush_delay_ms = 100
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def log(self, entry: LogEntry) -> None:
        """Buffer a redacted log entry; flush synchronously if threshold hit."""
        redacted = self._redact_entry(entry)
        should_flush = False
        with self._lock:
            self._buffer.append(json.dumps(redacted.model_dump(by_alias=True)))
            if len(self._buffer) >= self._max_buffer:
                should_flush = True
            elif self._timer is None:
                self._timer = threading.Timer(self._flush_delay_ms / 1000.0, self._flush)
                self._timer.start()
        if should_flush:
            self._flush()

    def close(self) -> None:
        """Cancel pending timer and flush remaining entries."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def _redact_entry(self, entry: LogEntry) -> LogEntry:
        updates: dict[str, Any] = {"message": redact_text(entry.message)}
        if entry.data is not None:
            redacted = redact_value_deep(entry.data)
            if isinstance(redacted, dict):
                updates["data"] = redacted
        return entry.model_copy(update=updates)

    def _flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            chunk = "\n".join(self._buffer) + "\n"
            self._buffer = []
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(chunk)
        except Exception:  # noqa: BLE001
            # Best-effort: log writes must never crash the agent loop.
            pass


__all__ = ["LogEntry", "LogLevel", "StructuredLogger"]
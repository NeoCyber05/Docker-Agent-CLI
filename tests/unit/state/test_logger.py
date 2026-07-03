"""Parity tests for logger — mirrors src/state/logger.ts."""

import json
import time
from pathlib import Path

import pytest

from docker_agent.state.logger import LogEntry, StructuredLogger


@pytest.fixture
def logger(tmp_path: Path) -> StructuredLogger:
    return StructuredLogger(str(tmp_path / "logs"), "sess-123")


def test_log_entry_redaction() -> None:
    entry = LogEntry(
        ts="2026-06-27T00:00:00Z",
        level="info",
        session_id="s",
        category="observation",
        message="ok",
        data={"password": "hunter2", "nested": {"api_key": "k"}, "safe": "keep"},
    )
    logger = StructuredLogger("/tmp", "s")
    redacted = logger._redact_entry(entry)
    assert redacted.data["password"] == "***"
    assert redacted.data["nested"]["api_key"] == "***"
    assert redacted.data["safe"] == "keep"


def test_logger_creates_file_on_flush(tmp_path: Path, logger: StructuredLogger) -> None:
    logger.log(
        LogEntry(ts="t", level="info", session_id="sess-123", category="c", message="m")
    )
    logger.close()
    log_file = tmp_path / "logs" / "sess-123.ndjson"
    assert log_file.exists()
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["category"] == "c"


def test_logger_buffers_until_threshold(tmp_path: Path) -> None:
    logger = StructuredLogger(str(tmp_path / "logs"), "sess")
    for i in range(49):
        logger.log(
            LogEntry(ts="t", level="info", session_id="sess", category="c", message=str(i))
        )
    # nothing flushed yet
    assert not (tmp_path / "logs" / "sess.ndjson").exists()
    logger.log(
        LogEntry(ts="t", level="info", session_id="sess", category="c", message="50")
    )
    # 50th entry triggers synchronous flush
    assert (tmp_path / "logs" / "sess.ndjson").exists()


def test_logger_timer_flush(tmp_path: Path) -> None:
    logger = StructuredLogger(str(tmp_path / "logs"), "sess")
    logger.log(
        LogEntry(ts="t", level="info", session_id="sess", category="c", message="delayed")
    )
    assert not (tmp_path / "logs" / "sess.ndjson").exists()
    time.sleep(0.15)
    assert (tmp_path / "logs" / "sess.ndjson").exists()


def test_close_cancels_timer_and_flushes(tmp_path: Path) -> None:
    logger = StructuredLogger(str(tmp_path / "logs"), "sess")
    logger.log(
        LogEntry(ts="t", level="info", session_id="sess", category="c", message="final")
    )
    logger.close()
    lines = (tmp_path / "logs" / "sess.ndjson").read_text().strip().split("\n")
    assert len(lines) == 1


def test_logger_appends_multiple_entries(tmp_path: Path) -> None:
    logger = StructuredLogger(str(tmp_path / "logs"), "sess")
    for i in range(5):
        logger.log(
            LogEntry(ts="t", level="info", session_id="sess", category="c", message=str(i))
        )
    logger.close()
    lines = (tmp_path / "logs" / "sess.ndjson").read_text().strip().split("\n")
    assert len(lines) == 5


def test_logger_swallows_flush_errors(logger: StructuredLogger) -> None:
    # logging should never crash the agent loop
    logger.log(
        LogEntry(ts="t", level="info", session_id="sess-123", category="c", message="m")
    )
    logger.close()


def test_log_entry_redacts_message_text() -> None:
    entry = LogEntry(
        ts="2026-06-27T00:00:00Z",
        level="info",
        session_id="s",
        category="turn_start",
        message="password=abc123",
    )
    logger = StructuredLogger("/tmp", "s")
    redacted = logger._redact_entry(entry)
    assert redacted.message == "password=***"


def test_log_entry_redacts_nested_string_values_in_data() -> None:
    entry = LogEntry(
        ts="2026-06-27T00:00:00Z",
        level="info",
        session_id="s",
        category="thought_delta",
        message="assistant text delta",
        data={"nested_text": "API_KEY=sk-live-xxxx"},
    )
    logger = StructuredLogger("/tmp", "s")
    redacted = logger._redact_entry(entry)
    assert redacted.data is not None
    assert redacted.data["nested_text"] == "API_KEY=***"
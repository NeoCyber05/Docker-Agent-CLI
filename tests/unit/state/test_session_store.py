"""Parity tests for session_store — mirrors src/state/SessionStore.ts."""

from pathlib import Path

from docker_agent.state.session_store import (
    SessionStore,
    format_sessions_list,
    redact_messages,
    session_cwd_mismatch_warning,
)
from docker_agent.types.message import (
    AssistantBlock,
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


def _user(text: str) -> Message:
    return UserMessage(content=text)


def _assistant_text(text: str) -> Message:
    return AssistantMessage(content=[AssistantBlock.model_validate({"type": "text", "text": text})])


def _tool_result(content: str) -> Message:
    return ToolResultMessage(tool_use_id="t1", content=content, is_error=False)


# --- redact_messages -----------------------------------------------------

def test_redact_messages_scrubs_user_text() -> None:
    redacted = redact_messages([_user("password=hunter2 host=db")])
    assert isinstance(redacted[0], UserMessage)
    assert redacted[0].content == "password=*** host=db"


def test_redact_messages_scrubs_json_in_tool_result() -> None:
    redacted = redact_messages([_tool_result('{"password":"hunter2"}')])
    assert isinstance(redacted[0], ToolResultMessage)
    assert '"password":"***"' in redacted[0].content


def test_redact_messages_scrubs_assistant_text() -> None:
    redacted = redact_messages([_assistant_text("POSTGRES_PASSWORD=hunter2")])
    assert isinstance(redacted[0], AssistantMessage)
    assert redacted[0].content[0].text == "POSTGRES_PASSWORD=***"


def test_redact_messages_object_replaces_whole_secret_value() -> None:
    # When a tool_use block input contains a secret key, the whole value becomes ***
    msg = AssistantMessage(
        content=[
            AssistantBlock.model_validate(
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "plan_stack",
                    "input": {"password": "hunter2", "host": "db"},
                }
            )
        ]
    )
    redacted = redact_messages([msg])
    assert redacted[0].content[0].input == {"password": "***", "host": "db"}


# --- save / read ---------------------------------------------------------

def test_save_and_read_round_trip(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    record = {
        "schema_version": 1,
        "id": "abc",
        "created_at": "t1",
        "updated_at": "t2",
        "cwd": "/tmp",
        "provider": "gemini",
        "model": "flash",
        "first_prompt": "hello",
        "stack_names": ["web"],
        "messages": [],
    }
    store.save(record)
    read = store.read("abc")
    assert read is not None
    assert read["id"] == "abc"
    assert read["model"] == "flash"


def test_save_preserves_original_created_at(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    store.save(
        {
            "schema_version": 1,
            "id": "abc",
            "created_at": "ORIGINAL",
            "updated_at": "t1",
            "cwd": "/tmp",
            "provider": "g",
            "first_prompt": "x",
            "stack_names": [],
            "messages": [],
        }
    )
    store.save(
        {
            "schema_version": 1,
            "id": "abc",
            "created_at": "NEW",
            "updated_at": "t2",
            "cwd": "/tmp",
            "provider": "g",
            "first_prompt": "x",
            "stack_names": [],
            "messages": [],
        }
    )
    read = store.read("abc")
    assert read["created_at"] == "ORIGINAL"


def test_read_missing_returns_none(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    assert store.read("missing") is None


def test_read_corrupt_returns_none(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    session_file = tmp_path / ".docker-agent" / "sessions" / "bad.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("not json")
    assert store.read("bad") is None


# --- list / index --------------------------------------------------------

def test_list_newest_first(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    for i, ts in enumerate(["2026-06-27T10:00:00Z", "2026-06-27T11:00:00Z"]):
        store.save(
            {
                "schema_version": 1,
                "id": f"s{i}",
                "created_at": ts,
                "updated_at": ts,
                "cwd": "/tmp",
                "provider": "g",
                "first_prompt": f"p{i}",
                "stack_names": [],
                "messages": [],
            }
        )
    entries = store.list()
    assert [e["id"] for e in entries] == ["s1", "s0"]


def test_list_returns_empty_when_index_missing(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / ".docker-agent"))
    assert store.list() == []


# --- cwd mismatch warning ------------------------------------------------

def test_cwd_mismatch_warning_when_different() -> None:
    record = {
        "schema_version": 1,
        "id": "x",
        "created_at": "t",
        "updated_at": "t",
        "cwd": "/a",
        "provider": "g",
        "first_prompt": "x",
        "stack_names": [],
        "messages": [],
    }
    assert "Resuming session saved in /a" in session_cwd_mismatch_warning(record, "/b")


def test_cwd_mismatch_warning_none_when_same() -> None:
    record = {
        "schema_version": 1,
        "id": "x",
        "created_at": "t",
        "updated_at": "t",
        "cwd": "/a",
        "provider": "g",
        "first_prompt": "x",
        "stack_names": [],
        "messages": [],
    }
    assert session_cwd_mismatch_warning(record, "/a") is None


# --- format_sessions_list ------------------------------------------------

def test_format_sessions_list_empty() -> None:
    assert format_sessions_list([]) == "No saved sessions."


def test_format_sessions_list_with_entries() -> None:
    entries = [
        {
            "id": "abc123",
            "created_at": "t",
            "updated_at": "2026-06-27T10:00:00Z",
            "first_prompt": "deploy nginx",
            "stack_names": ["web"],
        }
    ]
    text = format_sessions_list(entries)
    assert "Saved sessions (newest first):" in text
    assert "1. abc123" in text
    assert "deploy nginx" in text
    assert "Use /resume to pick a session" in text
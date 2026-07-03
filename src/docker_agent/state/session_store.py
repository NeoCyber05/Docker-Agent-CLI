"""JSON session persistence with secret redaction.

Parity: ``src/state/SessionStore.ts:1-345``.
"""

import contextlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from docker_agent.state.secret_redactor import (
    redact_text as _redact_string,
)
from docker_agent.state.secret_redactor import (
    redact_value_deep as _redact_value,
)
from docker_agent.types.message import (
    AssistantBlock,
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)

SCHEMA_VERSION = 1

SessionRecord = dict[str, Any]
SessionIndexEntry = dict[str, Any]


def _error_message(err: object) -> str:
    return str(err) if isinstance(err, Exception) else str(err)


def _warn(message: str) -> None:
    sys.stderr.write(f"[docker-agent] {message}\n")


def redact_messages(messages: list[Message]) -> list[Message]:
    """Return a deep copy of ``messages`` with secret values scrubbed."""
    out: list[Message] = []
    for msg in messages:
        if isinstance(msg, UserMessage):
            out.append(UserMessage(content=_redact_string(msg.content)))
        elif isinstance(msg, ToolResultMessage):
            out.append(
                ToolResultMessage.model_validate(
                    {
                        "tool_use_id": msg.tool_use_id,
                        "content": _redact_string(msg.content),
                        "is_error": msg.is_error,
                    }
                )
            )
        elif isinstance(msg, AssistantMessage):
            blocks: list[Any] = []
            for block in msg.content:
                data = block.model_dump(by_alias=True)
                if data["type"] == "text":
                    blocks.append(
                        AssistantBlock.model_validate(
                            {"type": "text", "text": _redact_string(data["text"])}
                        )
                    )
                elif data["type"] == "tool_use":
                    blocks.append(
                        AssistantBlock.model_validate(
                            {
                                "type": "tool_use",
                                "id": data["id"],
                                "name": data["name"],
                                "input": _redact_value(data["input"]),
                            }
                        )
                    )
                else:
                    blocks.append(block)
            out.append(AssistantMessage(content=blocks))
        else:
            out.append(msg)
    return out


def session_cwd_mismatch_warning(record: SessionRecord, cwd: str) -> str | None:
    if record.get("cwd") == cwd:
        return None
    return (
        f"Resuming session saved in {record['cwd']} "
        f"(current directory: {cwd}). Stack paths may differ."
    )


def format_sessions_list(entries: list[SessionIndexEntry]) -> str:
    if not entries:
        return "No saved sessions."
    lines = ["Saved sessions (newest first):"]
    for index, entry in enumerate(entries):
        stacks = (
            f"  stacks: {', '.join(entry['stack_names'])}" if entry["stack_names"] else ""
        )
        prompt = entry["first_prompt"]
        if len(prompt) > 72:
            prompt = prompt[:69] + "..."
        lines.append(f"{index + 1}. {entry['id']}")
        lines.append(f"   updated: {entry['updated_at']}{stacks}")
        lines.append(f"   prompt: {prompt}")
    lines.append("")
    lines.append("Use /resume to pick a session")
    return "\n".join(lines)


class SessionStore:
    """Owns ``.docker-agent/sessions/<id>.json`` and ``index.json``."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._sessions_dir = Path(root) / "sessions"
        self._index_path = self._sessions_dir / "index.json"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: SessionRecord) -> None:
        existing = self.read(record["id"])
        created_at = existing["created_at"] if existing else record["created_at"]
        redacted_messages = redact_messages(
            TypeAdapter(list[Message]).validate_python(record["messages"])
        )
        redacted: SessionRecord = {
            **record,
            "created_at": created_at,
            "messages": [m.model_dump(by_alias=True) for m in redacted_messages],
        }
        file_path = self._sessions_dir / f"{record['id']}.json"
        tmp_path = Path(f"{file_path}.tmp")
        try:
            tmp_path.write_text(
                json.dumps(redacted, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.chmod(tmp_path, 0o644)
            shutil.move(str(tmp_path), str(file_path))
        except Exception as err:  # noqa: BLE001
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
            _warn(f"SessionStore.save failed for session {record['id']}: {_error_message(err)}")
            return
        self._upsert_index(
            {
                "id": record["id"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
                "first_prompt": record["first_prompt"],
                "stack_names": record["stack_names"],
            }
        )

    def read(self, session_id: str) -> SessionRecord | None:
        file_path = self._sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            return None
        try:
            parsed = json.loads(file_path.read_text(encoding="utf-8"))
            return self._validate_record(parsed, str(file_path))
        except Exception as err:  # noqa: BLE001
            _warn(f"SessionStore.read failed for session {session_id}: {_error_message(err)}")
            return None

    def latest(self) -> SessionRecord | None:
        entries = self.list()
        if not entries:
            return None
        return self.read(entries[0]["id"])

    def list(self) -> list[SessionIndexEntry]:
        if not self._index_path.exists():
            return []
        try:
            parsed = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(parsed, list):
                _warn("SessionStore.list: index.json is not an array, ignoring")
                return []
            entries = [e for e in parsed if self._is_valid_index_entry(e)]
            entries.sort(
                key=lambda e: e["updated_at"], reverse=True
            )
            return entries
        except Exception as err:  # noqa: BLE001
            _warn(f"SessionStore.list failed: {_error_message(err)}")
            return []

    def _validate_record(self, obj: object, source: str) -> SessionRecord | None:
        if not isinstance(obj, dict):
            _warn(f"SessionStore: corrupt session file at {source} (not an object)")
            return None
        if obj.get("schema_version") != SCHEMA_VERSION:
            _warn(
                "SessionStore: unrecognised schemaVersion "
                f"{obj.get('schema_version')} at {source}; expected {SCHEMA_VERSION}"
            )
            return None
        required = [
            "id",
            "created_at",
            "updated_at",
            "cwd",
            "provider",
            "first_prompt",
            "stack_names",
            "messages",
        ]
        if not all(k in obj and isinstance(obj[k], type_for_key(k)) for k in required):
            _warn(f"SessionStore: corrupt session file at {source} (missing required fields)")
            return None
        return obj

    def _is_valid_index_entry(self, obj: object) -> bool:
        if not isinstance(obj, dict):
            return False
        return (
            isinstance(obj.get("id"), str)
            and isinstance(obj.get("created_at"), str)
            and isinstance(obj.get("updated_at"), str)
            and isinstance(obj.get("first_prompt"), str)
            and isinstance(obj.get("stack_names"), list)
        )

    def _upsert_index(self, entry: SessionIndexEntry) -> None:
        entries: list[SessionIndexEntry] = []
        if self._index_path.exists():
            try:
                parsed = json.loads(self._index_path.read_text(encoding="utf-8"))
                if isinstance(parsed, list):
                    entries = parsed
            except Exception:  # noqa: BLE001
                pass
        entries = [e for e in entries if e.get("id") != entry["id"]]
        entries.append(entry)
        tmp_path = Path(f"{self._index_path}.tmp")
        try:
            tmp_path.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.chmod(tmp_path, 0o644)
            shutil.move(str(tmp_path), str(self._index_path))
        except Exception as err:  # noqa: BLE001
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
            _warn(f"SessionStore.upsertIndex failed: {_error_message(err)}")


def type_for_key(key: str) -> type:
    mapping: dict[str, type] = {
        "id": str,
        "created_at": str,
        "updated_at": str,
        "cwd": str,
        "provider": str,
        "first_prompt": str,
        "stack_names": list,
        "messages": list,
    }
    return mapping.get(key, object)


__all__ = [
    "SessionIndexEntry",
    "SessionRecord",
    "SessionStore",
    "format_sessions_list",
    "redact_messages",
    "session_cwd_mismatch_warning",
]
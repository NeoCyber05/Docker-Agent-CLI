"""Pending confirmation transaction store for Docker MCP tools."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PendingKind = Literal["plan_review", "typed", "secrets_input", "permission"]


def _to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses, pydantic models and datetimes to JSON-safe values.

    ``private_payload`` can carry ``StagedSecretFile``/``StagedConfigFile`` dataclasses
    (e.g. auto-generated secrets), which ``json.dumps`` cannot serialize on its own.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _hydrate_staged_config_file(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    try:
        from docker_mcp_server.tools.shared.config_files import StagedConfigFile

        return StagedConfigFile(
            path=str(value["path"]),
            content=str(value["content"]),
            bytes=int(value["bytes"]),
        )
    except (KeyError, TypeError, ValueError):
        return value


def _hydrate_staged_secret_file(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    try:
        from docker_mcp_server.tools.shared.secret_staging import StagedSecretFile

        values = value["values"]
        if not isinstance(values, dict):
            return value
        return StagedSecretFile(
            path=str(value["path"]),
            values={str(key): str(item) for key, item in values.items()},
        )
    except (KeyError, TypeError, ValueError):
        return value


def _hydrate_private_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    hydrated = dict(value)
    config_files = hydrated.get("config_files")
    if isinstance(config_files, list):
        hydrated["config_files"] = [
            _hydrate_staged_config_file(item) for item in config_files
        ]
    secret_files = hydrated.get("secret_files")
    if isinstance(secret_files, list):
        hydrated["secret_files"] = [
            _hydrate_staged_secret_file(item) for item in secret_files
        ]
    return hydrated


class PendingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    cwd: str
    tool: str
    kind: PendingKind
    expires_at: datetime
    hash: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    private_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)

    def response_payload(self) -> dict[str, Any]:
        pending: dict[str, Any] = {
            "id": self.id,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "tool": self.tool,
            "kind": self.kind,
            "expires_at": self.expires_at.isoformat(),
            "display": self.payload,
        }
        if self.hash is not None:
            pending["hash"] = self.hash
        return {"status": "pending_confirmation", "pending_action": pending}


class PendingActionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self._actions: dict[str, PendingAction] = {}
        self._path = Path(path) if path is not None else None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._actions = {}
            return
        if not isinstance(raw, list):
            self._actions = {}
            return
        loaded: dict[str, PendingAction] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                action = PendingAction.model_validate(item)
            except Exception:
                continue
            action.private_payload = _hydrate_private_payload(action.private_payload)
            loaded[action.id] = action
        self._actions = loaded

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = []
        for action in self._actions.values():
            item = action.model_dump(mode="json")
            item["private_payload"] = _to_jsonable(action.private_payload)
            payload.append(item)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
        )
        tmp.replace(self._path)

    def add(self, action: PendingAction) -> PendingAction:
        self._ensure_loaded()
        self._actions[action.id] = action
        self._persist()
        return action

    def get(self, action_id: str) -> PendingAction | None:
        self._ensure_loaded()
        return self._actions.get(action_id)

    def consume(
        self,
        action_id: str,
        *,
        session_id: str,
        cwd: str,
        now: datetime | None = None,
    ) -> PendingAction:
        self._ensure_loaded()
        action = self._actions.get(action_id)
        if action is None:
            raise KeyError(action_id)
        current_time = now or datetime.now(UTC)
        if action.expires_at <= current_time:
            self._actions.pop(action_id, None)
            self._persist()
            raise TimeoutError(action_id)
        if action.session_id != session_id or action.cwd != cwd:
            raise PermissionError(action_id)
        self._actions.pop(action_id, None)
        self._persist()
        return action

    def sweep_expired(self, now: datetime | None = None) -> int:
        self._ensure_loaded()
        current_time = now or datetime.now(UTC)
        expired = [
            action_id
            for action_id, action in self._actions.items()
            if action.expires_at <= current_time
        ]
        for action_id in expired:
            self._actions.pop(action_id, None)
        if expired:
            self._persist()
        return len(expired)


__all__ = ["PendingAction", "PendingActionStore", "PendingKind"]


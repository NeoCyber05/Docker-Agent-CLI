"""Pending confirmation transaction store for Docker MCP tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PendingKind = Literal["plan_review", "typed", "secrets_input", "permission"]


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
    def __init__(self) -> None:
        self._actions: dict[str, PendingAction] = {}

    def add(self, action: PendingAction) -> PendingAction:
        self._actions[action.id] = action
        return action

    def get(self, action_id: str) -> PendingAction | None:
        return self._actions.get(action_id)

    def consume(
        self,
        action_id: str,
        *,
        session_id: str,
        cwd: str,
        now: datetime | None = None,
    ) -> PendingAction:
        action = self._actions.get(action_id)
        if action is None:
            raise KeyError(action_id)
        current_time = now or datetime.now(UTC)
        if action.expires_at <= current_time:
            self._actions.pop(action_id, None)
            raise TimeoutError(action_id)
        if action.session_id != session_id or action.cwd != cwd:
            raise PermissionError(action_id)
        self._actions.pop(action_id, None)
        return action

    def sweep_expired(self, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        expired = [
            action_id
            for action_id, action in self._actions.items()
            if action.expires_at <= current_time
        ]
        for action_id in expired:
            self._actions.pop(action_id, None)
        return len(expired)


__all__ = ["PendingAction", "PendingActionStore", "PendingKind"]

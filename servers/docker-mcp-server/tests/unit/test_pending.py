from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from docker_mcp_server.pending import PendingAction, PendingActionStore


def _action(**overrides: object) -> PendingAction:
    now = datetime.now(UTC)
    data = {
        "id": "pending-1",
        "session_id": "session-a",
        "cwd": "D:/work/project",
        "tool": "docker.deploy_stack",
        "kind": "plan_review",
        "hash": "hash-a",
        "expires_at": now + timedelta(minutes=5),
        "payload": {"compose_yaml": "services: {}"},
    }
    data.update(overrides)
    return PendingAction.model_validate(data)


def test_pending_action_store_is_single_use() -> None:
    store = PendingActionStore()
    action = store.add(_action())

    confirmed = store.consume(
        action.id,
        session_id="session-a",
        cwd="D:/work/project",
        now=datetime.now(UTC),
    )

    assert confirmed.id == action.id
    with pytest.raises(KeyError):
        store.consume(
            action.id,
            session_id="session-a",
            cwd="D:/work/project",
            now=datetime.now(UTC),
        )


def test_pending_action_store_rejects_wrong_session_or_cwd() -> None:
    store = PendingActionStore()
    action = store.add(_action())

    with pytest.raises(PermissionError):
        store.consume(
            action.id,
            session_id="other-session",
            cwd="D:/work/project",
            now=datetime.now(UTC),
        )

    assert store.get(action.id) is not None

    with pytest.raises(PermissionError):
        store.consume(
            action.id,
            session_id="session-a",
            cwd="D:/work/other",
            now=datetime.now(UTC),
        )


def test_pending_action_store_expires_and_removes_action() -> None:
    store = PendingActionStore()
    action = store.add(_action(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    with pytest.raises(TimeoutError):
        store.consume(
            action.id,
            session_id="session-a",
            cwd="D:/work/project",
            now=datetime.now(UTC),
        )

    assert store.get(action.id) is None




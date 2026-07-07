from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from docker_mcp_server.pending import PendingAction, PendingActionStore
from docker_mcp_server.tools.shared.config_files import StagedConfigFile
from docker_mcp_server.tools.shared.secret_staging import StagedSecretFile


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


def test_pending_action_store_persists_dataclass_secret_files(tmp_path: Path) -> None:
    """Regression: private_payload carrying StagedSecretFile must persist as JSON.

    Previously ``_persist`` called ``json.dumps`` on the raw dataclass and crashed with
    ``Object of type StagedSecretFile is not JSON serializable``, breaking every deploy
    that auto-generated secrets (e.g. a random MySQL password).
    """
    path = tmp_path / "pending-actions.json"
    store = PendingActionStore(path)
    action = store.add(
        _action(
            private_payload={
                "stack_name": "wordpress-stack",
                "compose_yaml": "services:\n  mysql: {}\n",
                "config_files": [
                    StagedConfigFile(
                        path="config/app.conf", content="debug=false\n", bytes=12
                    )
                ],
                "secret_files": [
                    StagedSecretFile(
                        path=str(tmp_path / ".env"),
                        values={"MYSQL_ROOT_PASSWORD": "s3cret"},
                    )
                ],
            }
        )
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert len(persisted) == 1
    config_files = persisted[0]["private_payload"]["config_files"]
    assert config_files[0]["content"] == "debug=false\n"
    secret_files = persisted[0]["private_payload"]["secret_files"]
    assert secret_files[0]["values"]["MYSQL_ROOT_PASSWORD"] == "s3cret"

    reloaded = PendingActionStore(path)
    confirmed = reloaded.consume(
        action.id,
        session_id="session-a",
        cwd="D:/work/project",
        now=datetime.now(UTC),
    )
    assert confirmed.private_payload["config_files"][0].path == "config/app.conf"
    assert confirmed.private_payload["secret_files"][0].path.endswith(".env")




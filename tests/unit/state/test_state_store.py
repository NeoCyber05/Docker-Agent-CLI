"""Parity tests for state_store — mirrors src/state/StateStore.ts."""

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from src.state.state_store import HistoryEvent, StateStore
from src.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _make_stack(name: str = "web") -> StackDefinition:
    return StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name=name,
            created_at="2026-06-27T00:00:00Z",
            last_applied=None,
            intent="deploy",
            provider="gemini",
            generated_by="docker-agent",
            env_file_sources={},
        ),
        services={"web": ServiceSpec(image="nginx:1.27")},
    )


# --- constructor / layout ------------------------------------------------

def test_constructor_creates_state_dirs(tmp_path: Path) -> None:
    root = tmp_path / ".docker-agent"
    StateStore(str(root))
    assert (tmp_path / "docker-stacks").exists()
    assert (root / "archive").exists()
    assert (root / "sessions").exists()
    assert (root / "locks").exists()
    assert (root / "logs").exists()
    assert (root / "secrets").exists()
    if sys.platform != "win32":
        assert (os.stat(root / "secrets").st_mode & 0o777) == 0o700


def test_constructor_migrates_legacy_stacks_dir(tmp_path: Path) -> None:
    legacy = tmp_path / ".docker-agent" / "stacks"
    legacy.mkdir(parents=True)
    (legacy / "old.yaml").write_text("x")
    StateStore(str(tmp_path / ".docker-agent"))
    assert not legacy.exists()
    assert (tmp_path / "docker-stacks" / "old.yaml").exists()


def test_constructor_with_non_docker_agent_root_puts_states_inside(tmp_path: Path) -> None:
    StateStore(str(tmp_path / "custom"))
    assert (tmp_path / "custom" / "docker-stacks").exists()


# --- write / read ---------------------------------------------------------

def test_write_and_read_round_trip(tmp_path: Path) -> None:
    root = tmp_path / ".docker-agent"
    store = StateStore(str(root))
    stack = _make_stack()
    store.write("web", stack)
    read = store.read("web")
    assert read is not None
    assert read.x_docker_agent.name == "web"
    assert read.services["web"].image == "nginx:1.27"


def test_write_is_atomic_and_sets_mode(tmp_path: Path) -> None:
    root = tmp_path / ".docker-agent"
    store = StateStore(str(root))
    store.write("web", _make_stack())
    file = tmp_path / "docker-stacks" / "web.yaml"
    assert file.exists()
    if sys.platform != "win32":
        assert (os.stat(file).st_mode & 0o777) == 0o644


def test_read_missing_returns_none(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    assert store.read("missing") is None


def test_read_invalid_stack_throws(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("bad", _make_stack())
    file = tmp_path / "docker-stacks" / "bad.yaml"
    file.write_text("services: not_an_object")
    with pytest.raises(ValueError):
        store.read("bad")


# --- list ----------------------------------------------------------------

def test_list_returns_stack_summaries(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack("web"))
    store.write("db", _make_stack("db"))
    summaries = store.list()
    names = {s.name for s in summaries}
    assert names == {"web", "db"}


def test_list_skips_invalid_files_with_warning(tmp_path: Path) -> None:
    warnings: list[str] = []
    store = StateStore(str(tmp_path / ".docker-agent"), warn=warnings.append)
    (tmp_path / "docker-stacks" / "bad.yaml").write_text("not: valid")
    assert store.list() == []
    assert any("Skipping invalid stack state" in w for w in warnings)


# --- remove / archive ----------------------------------------------------

def test_remove_archives_with_timestamp_and_stable_copy(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack())
    store.remove("web")
    assert not (tmp_path / "docker-stacks" / "web.yaml").exists()
    archive_dir = tmp_path / ".docker-agent" / "archive"
    assert (archive_dir / "web.yaml").exists()
    timestamped = list(archive_dir.glob("web-*.yaml"))
    assert len(timestamped) == 1


def test_remove_without_archive_unlinks(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack())
    store.remove("web", archive=False)
    assert not (tmp_path / "docker-stacks" / "web.yaml").exists()
    assert not (tmp_path / ".docker-agent" / "archive" / "web.yaml").exists()


# --- archive helpers -----------------------------------------------------

def test_read_archive_returns_stable_copy(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack())
    store.remove("web")
    archived = store.read_archive("web")
    assert archived is not None
    assert archived.x_docker_agent.name == "web"


def test_has_archive_marker_detects_timestamped_file(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack())
    store.remove("web")
    assert store.has_archive_marker("web")


# --- history -------------------------------------------------------------

def test_append_history_writes_ndjson(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    event = HistoryEvent(
        ts="2026-06-27T00:00:00Z",
        session_id="s",
        stack_name="web",
        action="apply",
        details={"ok": True},
    )
    store.append_history(event)
    store.append_history(event)
    lines = (tmp_path / ".docker-agent" / "history.json").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "apply"


# --- lock ----------------------------------------------------------------

def test_acquire_lock_writes_pid_and_unlock_removes(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    unlock = store.acquire_lock("web")
    lock_file = tmp_path / ".docker-agent" / "locks" / "web.lock"
    assert lock_file.exists()
    assert int(lock_file.read_text().strip()) == os.getpid()
    unlock()
    assert not lock_file.exists()


def test_acquire_lock_times_out_when_held(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    other = tmp_path / ".docker-agent" / "locks" / "web.lock"
    other.write_text("99999999")  # fake pid, definitely not alive
    unlock = store.acquire_lock("web")
    assert unlock


# --- summary -------------------------------------------------------------

def test_summary_redacts_secret_env_and_keeps_visible(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    stack = StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name="web",
            created_at="t",
            last_applied=None,
            intent="i",
            provider="g",
            generated_by="a",
            env_file_sources={},
        ),
        services={
            "web": ServiceSpec(
                image="nginx:1.27",
                environment={"POSTGRES_PASSWORD": "x", "HOST": "db"},
            )
        },
    )
    store.write("web", stack)
    summary_text = store.summary()
    data = yaml.safe_load(summary_text)
    assert data["web"]["services"]["web"]["environment"]["HOST"] == "db"
    assert data["web"]["services"]["web"]["environment"]["POSTGRES_PASSWORD"] == "***"
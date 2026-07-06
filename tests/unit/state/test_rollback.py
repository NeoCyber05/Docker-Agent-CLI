"""Parity tests for rollback â€” mirrors src/state/rollback.ts."""

from pathlib import Path

import yaml

from docker_mcp_server.state.rollback import (
    KnownGood,
    capture_known_good,
    plan_rollback,
)
from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _make_stack(name: str) -> StackDefinition:
    return StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name=name,
            created_at="t",
            last_applied=None,
            intent="i",
            provider="g",
            generated_by="a",
            env_file_sources={},
        ),
        services={name: ServiceSpec(image="nginx:1.27")},
    )


def test_capture_known_good_live_file(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack("web"))
    ctx = {"state_store": store}
    known = capture_known_good("web", ctx)
    assert known.previous is not None
    assert known.existed_expected is True
    assert known.recoverable is True
    assert known.previous_yaml is not None


def test_capture_known_good_archive_fallback(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack("web"))
    store.remove("web")  # archives
    ctx = {"state_store": store}
    known = capture_known_good("web", ctx)
    assert known.previous is not None
    assert known.recoverable is True


def test_capture_known_good_archive_marker_only(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write("web", _make_stack("web"))
    store.remove("web")
    # delete stable archive but keep timestamped marker
    stable = tmp_path / ".docker-agent" / "archive" / "web.yaml"
    stable.unlink()
    ctx = {"state_store": store}
    known = capture_known_good("web", ctx)
    assert known.previous is None
    assert known.existed_expected is True
    assert known.recoverable is False


def test_capture_known_good_first_time_create(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    ctx = {"state_store": store}
    known = capture_known_good("web", ctx)
    assert known.previous is None
    assert known.existed_expected is False
    assert known.recoverable is False


def test_plan_rollback_restore_previous() -> None:
    known = KnownGood(
        previous=_make_stack("web"),
        existed_expected=True,
        recoverable=True,
        previous_yaml=yaml.safe_dump(_make_stack("web").model_dump(by_alias=True)),
    )
    plan = plan_rollback(known, "web")
    assert plan.strategy == "restore_previous"
    assert plan.compose_yaml == known.previous_yaml


def test_plan_rollback_teardown_partial() -> None:
    known = KnownGood(
        previous=None, existed_expected=False, recoverable=False
    )
    plan = plan_rollback(known, "web")
    assert plan.strategy == "teardown_partial"


def test_plan_rollback_none() -> None:
    known = KnownGood(
        previous=None, existed_expected=True, recoverable=False
    )
    plan = plan_rollback(known, "web")
    assert plan.strategy == "none"
    assert "no recoverable prior state" in plan.reason

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docker_mcp_server.config import project_state_dir, stack_states_dir
from docker_mcp_server.server import (
    deploy_stack_payload,
    list_stacks_payload,
    pending_confirmation_stub,
)
from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.tools.plan_stack import PlanStackResultBlocked, PlanStackResultOk
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _plan_stack_tuple(
    result: PlanStackResultOk | PlanStackResultBlocked,
    progress: list[str] | None = None,
) -> tuple[PlanStackResultOk | PlanStackResultBlocked, list[str]]:
    return result, progress or ["Validating service spec..."]


def _preflight_artifact() -> dict[str, str]:
    return {
        "kind": "validation",
        "label": "Preflight report",
        "language": "text",
        "content": "Preflight passed\nChecks: image, config\nWarnings: 0\nIssues: 0",
    }


def _write_stack(project: Path, name: str) -> None:
    store = StateStore(project_state_dir(project), states_dir=stack_states_dir(project))
    store.write(
        name,
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
                name=name,
                created_at="x",
                last_applied=None,
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={},
            ),
            services={"web": ServiceSpec(image="nginx")},
        ),
    )


def test_list_stacks_payload_uses_existing_state_store(tmp_path: Path) -> None:
    _write_stack(tmp_path, "web")

    payload = list_stacks_payload(str(tmp_path))

    assert payload == {
        "stacks": [
            {
                "name": "web",
                "serviceCount": 1,
                "lastApplied": None,
            }
        ]
    }


def test_pending_confirmation_stub_matches_contract(tmp_path: Path) -> None:
    payload = pending_confirmation_stub(
        cwd=str(tmp_path),
        session_id="session-a",
        tool="docker.deploy_stack",
    )

    assert payload["status"] == "pending_confirmation"
    pending = payload["pending_action"]
    assert pending["session_id"] == "session-a"
    assert pending["cwd"] == str(tmp_path)
    assert pending["tool"] == "docker.deploy_stack"
    assert pending["kind"] == "plan_review"
    assert pending["display"]["artifacts"][0]["content"] == "services: {}"
    assert "expires_at" in pending


@pytest.mark.asyncio
async def test_commit_action_approves_stub_pending_action(tmp_path: Path) -> None:
    payload = pending_confirmation_stub(
        cwd=str(tmp_path),
        session_id="session-a",
        tool="docker.deploy_stack",
    )

    from docker_mcp_server.server import commit_action_payload

    result = await commit_action_payload(
        pending_action_id=payload["pending_action"]["id"],
        session_id="session-a",
        cwd=str(tmp_path),
        decision="approve",
    )

    assert result == {
        "status": "ok",
        "result": "confirmed docker.deploy_stack",
    }


@pytest.mark.asyncio
async def test_deploy_stack_returns_pending_action_with_apply_payload(
    tmp_path: Path,
) -> None:
    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
        preflight_artifact=_preflight_artifact(),
        preflight_details={
            "status": "passed",
            "checks": ["image", "config"],
            "warnings": 0,
            "issues": 0,
        },
    )

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(return_value=_plan_stack_tuple(plan)),
    ):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:1.27",
                }
            ],
        )

    assert payload["status"] == "pending_confirmation"
    pending = payload["pending_action"]
    assert pending["tool"] == "docker.deploy_stack"
    assert pending["kind"] == "plan_review"
    assert pending["hash"] == "hash-a"
    assert pending["display"]["artifacts"][0]["label"] == "Preflight report"
    assert pending["display"]["artifacts"][1]["content"] == plan.compose_yaml
    assert payload["progress"] == ["Validating service spec..."]


@pytest.mark.asyncio
async def test_deploy_stack_missing_project_policy_returns_initialize_permission(
    tmp_path: Path,
) -> None:
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(return_value=_plan_stack_tuple(plan)),
    ):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:1.27",
                }
            ],
        )

    assert payload["status"] == "pending_confirmation"
    pending = payload["pending_action"]
    assert pending["tool"] == "initialize_project_policy"
    assert pending["kind"] == "permission"
    assert pending["display"]["path"] == str(tmp_path / "project-policies.yaml")
    assert "project:\n  deny: []\n  require: []\n" in pending["display"]["content"]


@pytest.mark.asyncio
async def test_commit_action_initialize_project_policy_creates_file_and_replans(
    tmp_path: Path,
) -> None:
    """Regression: approving the policy-init must return the real deploy plan.

    Previously the cached draft was dropped once the policy file was created, so
    the caller had to remember to call docker.deploy_stack a second time. If it
    didn't, the user was left waiting on a plan_review that was never created —
    the agent would eventually claim "plan sent for review" with nothing to
    review, and the turn only ended after the LLM finished rambling.
    """
    from docker_mcp_server.server import commit_action_payload

    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(return_value=_plan_stack_tuple(plan)),
    ):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:1.27",
                }
            ],
        )
        assert payload["pending_action"]["tool"] == "initialize_project_policy"

        result = await commit_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    policy_path = tmp_path / "project-policies.yaml"
    assert policy_path.exists()
    assert "project:" in policy_path.read_text(encoding="utf-8")

    assert result["status"] == "pending_confirmation"
    pending = result["pending_action"]
    assert pending["tool"] == "docker.deploy_stack"
    assert pending["kind"] == "plan_review"
    assert pending["hash"] == "hash-a"
    assert pending["display"]["artifacts"][-2]["content"] == plan.compose_yaml


@pytest.mark.asyncio
async def test_commit_action_initialize_project_policy_without_draft_just_creates_file(
    tmp_path: Path,
) -> None:
    """Direct policy-init pending actions (no cached draft) keep the old contract."""
    from docker_mcp_server.server import _pending_initialize_project_policy, commit_action_payload

    payload = _pending_initialize_project_policy(cwd=str(tmp_path), session_id="session-a")

    result = await commit_action_payload(
        pending_action_id=payload["pending_action"]["id"],
        session_id="session-a",
        cwd=str(tmp_path),
        decision="approve",
    )
    policy_path = tmp_path / "project-policies.yaml"
    assert policy_path.exists()
    assert result["status"] == "ok"
    assert "created" in result["result"]


def test_capabilities_include_docker_domain_instructions() -> None:
    from docker_mcp_server.server import capabilities_payload

    instructions = capabilities_payload()["instructions"]

    assert isinstance(instructions, str)
    assert "Every Docker deployment or stack change MUST go through `docker.deploy_stack`" in (
        instructions
    )
    assert "catalogId" in instructions


def test_capabilities_include_full_docker_tool_surface() -> None:
    from docker_mcp_server.server import capabilities_payload

    names = {tool["name"] for tool in capabilities_payload()["tools"]}

    assert {
        "docker.deploy_stack",
        "docker.validate_spec",
        "docker.resolve_dependency",
        "docker.list_stacks",
        "docker.inspect_drift",
        "docker.get_stack_status",
        "docker.get_logs",
        "docker.get_health",
        "docker.exec_docker",
        "docker.destroy_stack",
        "docker.destroy_all_stacks",
        "docker.stop_stack",
        "docker.remove_container",
        "docker.remediate_drift",
    }.issubset(names)


@pytest.mark.asyncio
async def test_commit_action_approve_runs_apply_transaction(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from docker_mcp_server.server import commit_action_payload

    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )
    revalidate = AsyncMock(return_value=_plan_stack_tuple(plan))
    apply_transaction = AsyncMock(
        return_value=SimpleNamespace(ok=True, result_message="Stack applied.", rollback=None)
    )

    with patch("docker_mcp_server.server._run_plan_stack", revalidate):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[{"name": "web", "kind": "custom", "image": "nginx:1.27"}],
        )

    with (
        patch("docker_mcp_server.server._run_plan_stack", revalidate),
        patch("docker_mcp_server.server.run_apply_transaction", apply_transaction),
    ):
        result = await commit_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    assert result == {
        "status": "ok",
        "result": "Stack applied.",
        "ok": True,
        "events": [],
    }
    assert apply_transaction.await_count == 1


@pytest.mark.asyncio
async def test_commit_action_failure_returns_rollback_action(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from docker_mcp_server.server import commit_action_payload

    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )
    revalidate = AsyncMock(return_value=_plan_stack_tuple(plan))
    rollback = SimpleNamespace(id="rollback-1")
    apply_transaction = AsyncMock(
        return_value=SimpleNamespace(
            ok=False,
            result_message="apply failed",
            rollback=rollback,
        )
    )

    with patch("docker_mcp_server.server._run_plan_stack", revalidate):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[{"name": "web", "kind": "custom", "image": "nginx:1.27"}],
        )

    with (
        patch("docker_mcp_server.server._run_plan_stack", revalidate),
        patch("docker_mcp_server.server.run_apply_transaction", apply_transaction),
    ):
        result = await commit_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    assert result["status"] == "error"
    assert result["ok"] is False
    assert result["rollback_action"] == {
        "id": "rollback-1",
        "tool": "docker.rollback_action",
    }


@pytest.mark.asyncio
async def test_commit_action_missing_pending_returns_clean_error(tmp_path: Path) -> None:
    """A stale/unknown approval must not raise a raw KeyError to the caller."""
    from docker_mcp_server.server import commit_action_payload

    result = await commit_action_payload(
        pending_action_id="does-not-exist",
        session_id="session-a",
        cwd=str(tmp_path),
        decision="approve",
    )

    assert result["status"] == "error"
    assert "no matching pending action" in result["result"].lower()


@pytest.mark.asyncio
async def test_commit_action_expired_pending_returns_clean_error(tmp_path: Path) -> None:
    """A plan that expired while the user deliberated must degrade gracefully.

    Regression: the old code let ``consume`` raise ``TimeoutError`` which surfaced
    as a cryptic ``Error executing tool docker.commit_action: <id>`` message, so the
    agent looped on re-planning instead of telling the user the plan expired.
    """
    from docker_mcp_server.server import commit_action_payload, pending_confirmation_stub

    payload = pending_confirmation_stub(
        cwd=str(tmp_path),
        session_id="session-a",
        tool="docker.deploy_stack",
        ttl_seconds=-1,
    )

    result = await commit_action_payload(
        pending_action_id=payload["pending_action"]["id"],
        session_id="session-a",
        cwd=str(tmp_path),
        decision="approve",
    )

    assert result["status"] == "error"
    assert "expired" in result["result"].lower()


@pytest.mark.asyncio
async def test_commit_action_session_mismatch_returns_clean_error(tmp_path: Path) -> None:
    from docker_mcp_server.server import commit_action_payload, pending_confirmation_stub

    payload = pending_confirmation_stub(
        cwd=str(tmp_path),
        session_id="session-a",
        tool="docker.deploy_stack",
    )

    result = await commit_action_payload(
        pending_action_id=payload["pending_action"]["id"],
        session_id="session-b",
        cwd=str(tmp_path),
        decision="approve",
    )

    assert result["status"] == "error"
    assert "different session" in result["result"].lower()


@pytest.mark.asyncio
async def test_rollback_action_executes_stored_transaction(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from docker_mcp_server.server import _ROLLBACKS, rollback_action_payload

    rollback_transaction = SimpleNamespace(id="rollback-1")
    _ROLLBACKS["rollback-1"] = rollback_transaction
    rollback_transaction_runner = AsyncMock(
        return_value=SimpleNamespace(ok=True, result_message="rollback succeeded")
    )

    with patch(
        "docker_mcp_server.server.run_rollback_transaction",
        rollback_transaction_runner,
    ):
        result = await rollback_action_payload(
            rollback_action_id="rollback-1",
            session_id="session-a",
            cwd=str(tmp_path),
        )

    assert result == {
        "status": "ok",
        "result": "rollback succeeded",
        "ok": True,
        "events": [],
    }
    assert rollback_transaction_runner.await_count == 1


@pytest.mark.asyncio
async def test_deploy_stack_blocked_includes_progress_and_preflight(
    tmp_path: Path,
) -> None:
    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    blocked = PlanStackResultBlocked(
        reason="invalid_spec",
        preflight_artifact={
            "kind": "validation",
            "label": "Preflight report",
            "language": "text",
            "content": "Preflight blocked\nChecks: image\nWarnings: 0\nIssues: 1",
        },
        preflight_details={
            "status": "blocked",
            "checks": ["image"],
            "warnings": 0,
            "issues": 1,
        },
    )
    progress = ["Validating service spec...", "image manifest not found"]

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(return_value=(blocked, progress)),
    ):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[{"name": "web", "kind": "custom", "image": "nginx:1.27"}],
        )

    assert payload["status"] == "blocked"
    assert payload["progress"] == progress
    assert payload["preflight"]["label"] == "Preflight report"
    assert payload["validation"]["status"] == "blocked"
    assert "pending_action" not in payload


@pytest.mark.asyncio
async def test_commit_action_revalidation_blocked_does_not_apply(
    tmp_path: Path,
) -> None:
    from docker_mcp_server.server import commit_action_payload

    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )
    blocked = PlanStackResultBlocked(reason="port_conflict")
    apply_transaction = AsyncMock()

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(side_effect=[_plan_stack_tuple(plan), (blocked, ["Validating service spec..."])]),
    ):
        payload = await deploy_stack_payload(
            cwd=str(tmp_path),
            session_id="session-a",
            stackName="web",
            intent="deploy nginx",
            services=[{"name": "web", "kind": "custom", "image": "nginx:1.27"}],
        )

    with (
        patch(
            "docker_mcp_server.server._run_plan_stack",
            AsyncMock(return_value=(blocked, ["Validating service spec..."])),
        ),
        patch("docker_mcp_server.server.run_apply_transaction", apply_transaction),
    ):
        result = await commit_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    assert result["status"] == "blocked"
    assert result["progress"] == ["Validating service spec..."]
    assert apply_transaction.await_count == 0




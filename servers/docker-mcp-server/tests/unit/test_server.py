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
from docker_mcp_server.tools.plan_stack import PlanStackResultOk
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _write_stack(project: Path, name: str) -> None:
    store = StateStore(project_state_dir(project), states_dir=stack_states_dir(project))
    store.write(
        name,
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
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
async def test_confirm_action_approves_stub_pending_action(tmp_path: Path) -> None:
    payload = pending_confirmation_stub(
        cwd=str(tmp_path),
        session_id="session-a",
        tool="docker.deploy_stack",
    )

    from docker_mcp_server.server import confirm_action_payload

    result = await confirm_action_payload(
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
    )

    with patch(
        "docker_mcp_server.server._run_plan_stack",
        AsyncMock(return_value=plan),
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
    assert pending["display"]["artifacts"][0]["content"] == plan.compose_yaml


@pytest.mark.asyncio
async def test_confirm_action_approve_runs_apply_transaction_for_compatibility(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )
    apply = AsyncMock(
        return_value=SimpleNamespace(ok=True, result_message="Stack applied.", rollback=None)
    )
    revalidate = AsyncMock(return_value=plan)

    with patch("docker_mcp_server.server._run_plan_stack", revalidate):
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

    with (
        patch("docker_mcp_server.server._run_plan_stack", revalidate),
        patch("docker_mcp_server.server.run_apply_transaction", apply),
    ):
        from docker_mcp_server.server import confirm_action_payload

        result = await confirm_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    assert result["status"] == "ok"
    assert result["result"] == "Stack applied."
    assert revalidate.await_count >= 2
    assert apply.await_count == 1
    params = apply.await_args.args[0]
    assert params.stack_name == "web"
    assert params.desired_yaml == plan.compose_yaml


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
    revalidate = AsyncMock(return_value=plan)
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
    revalidate = AsyncMock(return_value=plan)
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
async def test_confirm_action_remains_backward_compatible(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from docker_mcp_server.server import confirm_action_payload

    (tmp_path / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")
    plan = PlanStackResultOk(
        compose_yaml="services:\n  web:\n    image: nginx:1.27\n",
        hash="hash-a",
    )
    revalidate = AsyncMock(return_value=plan)
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
        result = await confirm_action_payload(
            pending_action_id=payload["pending_action"]["id"],
            session_id="session-a",
            cwd=str(tmp_path),
            decision="approve",
        )

    assert result["status"] == "ok"
    assert result["result"] == "Stack applied."
    assert apply_transaction.await_count == 1




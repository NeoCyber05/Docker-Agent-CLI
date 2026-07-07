from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from docker_mcp_server.apply_with_rollback import (
    ApplyWithRollbackParams,
    RollbackTransaction,
    run_apply_transaction,
    run_rollback_transaction,
)
from docker_mcp_server.config import (
    load_user_config,
    project_state_dir,
    stack_states_dir,
)
from docker_mcp_server.formatting import format_plan_blocker
from docker_mcp_server.instructions import DOCKER_INSTRUCTIONS
from docker_mcp_server.pending import PendingAction, PendingActionStore
from docker_mcp_server.policy.defaults import ensure_global_policy
from docker_mcp_server.policy.policy_engine import PolicyEngine
from docker_mcp_server.services.docker.compose_runner import ComposeRunner
from docker_mcp_server.services.docker.engine_client import create_engine_client
from docker_mcp_server.state.secret_redactor import scrub_line
from docker_mcp_server.state.state_store import HistoryEvent, StateStore
from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress
from docker_mcp_server.tools.destroy_all_stacks import destroy_all_stacks
from docker_mcp_server.tools.destroy_stack import destroy_stack
from docker_mcp_server.tools.exec_docker import exec_docker
from docker_mcp_server.tools.get_health import get_health
from docker_mcp_server.tools.get_logs import get_logs
from docker_mcp_server.tools.get_stack_status import get_stack_status
from docker_mcp_server.tools.inspect_drift import inspect_drift
from docker_mcp_server.tools.list_stacks import list_stacks
from docker_mcp_server.tools.plan_stack import PlanStackResultOk, plan_stack
from docker_mcp_server.tools.remediate_drift import remediate_drift
from docker_mcp_server.tools.remove_container import remove_container
from docker_mcp_server.tools.resolve_dependency import resolve_dependency
from docker_mcp_server.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_mcp_server.tools.shared.spec_schemas import StackDraft
from docker_mcp_server.tools.stop_stack import stop_stack
from docker_mcp_server.tools.validate_spec import validate_spec

# Pending actions gate on an interactive human approval, so the TTL must cover
# realistic deliberation time. The previous 5-minute window routinely expired
# mid-review, causing commit to fail and the agent to loop on re-planning.
_PENDING_TTL_SECONDS = 1800

_PENDING_STORES: dict[str, PendingActionStore] = {}
_ROLLBACKS: dict[str, RollbackTransaction] = {}
_READ_ONLY_TOOLS = [
    validate_spec,
    resolve_dependency,
    list_stacks,
    inspect_drift,
    get_stack_status,
    get_logs,
    get_health,
]
_PERMISSION_TOOLS = [exec_docker]
_HIGH_RISK_PERMISSION_TOOLS = [remediate_drift]
_MUTATING_TOOLS = [destroy_stack, destroy_all_stacks, stop_stack, remove_container]
_PROJECT_POLICY_FILENAME = "project-policies.yaml"
_PROJECT_POLICY_DEFAULT_CONTENT = "project:\n  deny: []\n  require: []\n"


class _UnavailableDockerEngine:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def __getattr__(self, name: str) -> Any:
        message = f"Docker engine is unavailable for {name}: {self._error}"
        raise RuntimeError(message) from self._error


def _state_store(cwd: str) -> StateStore:
    return StateStore(project_state_dir(cwd), states_dir=stack_states_dir(cwd))


def _pending_store(cwd: str) -> PendingActionStore:
    root = Path(project_state_dir(cwd))
    key = str(root.resolve())
    store = _PENDING_STORES.get(key)
    if store is None:
        store = PendingActionStore(root / "pending-actions.json")
        _PENDING_STORES[key] = store
    return store


def _engine_client() -> Any:
    try:
        return create_engine_client()
    except Exception as err:  # noqa: BLE001 - defer until a Docker call is actually needed
        return _UnavailableDockerEngine(err)


def _tool_context(
    *,
    cwd: str,
    session_id: str,
    provider_name: str = "mcp",
    model: str | None = None,
) -> ToolContext:
    return ToolContext(
        cwd=cwd,
        state_store=_state_store(cwd),
        docker_engine=_engine_client(),
        compose_runner=ComposeRunner(cwd),
        abort_signal=asyncio.Event(),
        session_id=session_id,
        provider_name=provider_name,
        model=model,
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


async def _drain_tool(tool: Any, parsed: Any, ctx: ToolContext) -> tuple[Any, list[str]]:
    progress: list[str] = []
    result: Any = None
    async for item in tool.call(parsed, ctx):
        if isinstance(item, ToolDone):
            result = item.result
        elif isinstance(item, ToolProgress):
            progress.append(item.msg)
    return result, progress


async def _run_plan_stack(input_data: StackDraft, ctx: ToolContext) -> tuple[Any, list[str]]:
    return await _drain_tool(plan_stack, input_data, ctx)


def _policy_engine(cwd: str) -> PolicyEngine:
    ensure_global_policy()
    return PolicyEngine(
        user_config=load_user_config(),
        project_policy_path=str(Path(cwd) / "project-policies.yaml"),
    )


def _policy_block_message(violations: list[Any]) -> str:
    msgs = "\n".join(f"[{v.service}] {v.rule}: {v.message}" for v in violations)
    return f"Policy violation(s) detected. Deployment is blocked:\n{msgs}"


def _project_policy_path(cwd: str) -> Path:
    return Path(cwd) / _PROJECT_POLICY_FILENAME


def _has_missing_project_policy_violation(violations: list[Any]) -> bool:
    return any(getattr(item, "rule", "") == "project_policy_missing" for item in violations)


def _pending_initialize_project_policy(
    *,
    cwd: str,
    session_id: str,
    ttl_seconds: int = _PENDING_TTL_SECONDS,
    draft: StackDraft | None = None,
    provider_name: str = "mcp",
    model: str | None = None,
) -> dict[str, Any]:
    target = _project_policy_path(cwd)
    private_payload: dict[str, Any] = {
        "path": str(target),
        "content": _PROJECT_POLICY_DEFAULT_CONTENT,
    }
    if draft is not None:
        # Stash the in-flight deploy draft so approval can auto-replan instead of
        # dropping it — otherwise the caller must remember to re-call deploy_stack,
        # and the LLM often forgets, leaving the user waiting on a plan that never
        # gets created (see: agent stalls after policy init with no real plan).
        private_payload["draft"] = draft.model_dump(by_alias=True, exclude_none=True)
        private_payload["provider_name"] = provider_name
        private_payload["model"] = model
    action = PendingAction(
        id=str(uuid4()),
        session_id=session_id,
        cwd=cwd,
        tool="initialize_project_policy",
        kind="permission",
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        payload={
            "reason": "Project policy file (project-policies.yaml) is missing",
            "path": str(target),
            "content": _PROJECT_POLICY_DEFAULT_CONTENT,
        },
        private_payload=private_payload,
    )
    return _pending_store(cwd).add(action).response_payload()


async def _approve_initialize_project_policy(action: PendingAction) -> dict[str, Any]:
    path = Path(str(action.private_payload.get("path") or ""))
    content = str(action.private_payload.get("content") or _PROJECT_POLICY_DEFAULT_CONTENT)
    if not path:
        return {"status": "error", "result": "initialize_project_policy missing target path"}
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    draft_dict = action.private_payload.get("draft")
    if not isinstance(draft_dict, dict):
        return {"status": "ok", "result": f"created {path}"}

    # Policy is satisfied now — replan immediately so this hop returns the real
    # deploy plan for review instead of leaving the caller to guess it must call
    # docker.deploy_stack again.
    draft = StackDraft.model_validate(draft_dict)
    provider_name = str(action.private_payload.get("provider_name") or "mcp")
    model = action.private_payload.get("model")
    model = model if isinstance(model, str) else None
    ctx, result, progress = await _plan_deploy(
        cwd=action.cwd,
        session_id=action.session_id,
        provider_name=provider_name,
        model=model,
        draft=draft,
    )
    return await _finalize_plan_result(
        ctx=ctx,
        result=result,
        progress=progress,
        draft=draft,
        session_id=action.session_id,
        cwd=action.cwd,
        provider_name=provider_name,
        model=model,
    )


def _plan_confirm_payload(
    plan_result: PlanStackResultOk,
    parsed_input: StackDraft,
    ctx: ToolContext,
) -> dict[str, Any]:
    secret_keys = collect_secret_keys(
        parsed_input.stack_name,
        SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store),
    )
    artifacts: list[dict[str, Any]] = []
    if plan_result.preflight_artifact is not None:
        artifacts.append(plan_result.preflight_artifact)
    artifacts.extend(
        [
            {
                "kind": "manifest",
                "label": "Compose YAML",
                "language": "yaml",
                "content": plan_result.compose_yaml,
            },
            {
                "kind": "diff",
                "label": "Stack diff",
                "content": _jsonable(plan_result.diff),
            },
        ]
    )
    payload: dict[str, Any] = {
        "title": f"Deploy Docker stack {parsed_input.stack_name}",
        "summary": parsed_input.intent,
        "artifacts": artifacts,
        "hash": plan_result.hash,
    }
    if plan_result.auto_generated_secrets:
        payload["auto_generated_secrets"] = [
            {"service": s.service, "keys": s.keys} for s in plan_result.auto_generated_secrets
        ]
    if plan_result.config_files:
        payload["config_files"] = [
            {
                "path": f.path,
                "content": "\n".join(
                    scrub_line(line, secret_keys) for line in f.content.split("\n")
                ),
                "bytes": f.bytes,
            }
            for f in plan_result.config_files
        ]
    return payload


async def _plan_deploy(
    *,
    cwd: str,
    session_id: str,
    provider_name: str,
    model: str | None,
    draft: StackDraft,
) -> tuple[ToolContext, PlanStackResultOk | dict[str, Any], list[str]]:
    ctx = _tool_context(
        cwd=cwd,
        session_id=session_id,
        provider_name=provider_name,
        model=model,
    )
    result, progress = await _run_plan_stack(draft, ctx)
    if getattr(result, "blocked", False):
        blocked: dict[str, Any] = {
            "status": "blocked",
            "result": format_plan_blocker(result),
            "progress": progress,
        }
        preflight = getattr(result, "preflight_artifact", None)
        if preflight is not None:
            blocked["preflight"] = preflight
        preflight_details = getattr(result, "preflight_details", None)
        if preflight_details is not None:
            blocked["validation"] = preflight_details
        return ctx, blocked, progress
    plan_result: PlanStackResultOk = result
    violations = _policy_engine(cwd).evaluate(plan_result.compose_yaml)
    if violations:
        if _has_missing_project_policy_violation(violations):
            pending = _pending_initialize_project_policy(
                cwd=cwd,
                session_id=session_id,
                draft=draft,
                provider_name=provider_name,
                model=model,
            )
            return ctx, {
                **pending,
                "progress": progress,
            }, progress
        return ctx, {
            "status": "blocked",
            "result": _policy_block_message(violations),
            "progress": progress,
        }, progress
    return ctx, plan_result, progress


def list_stacks_payload(cwd: str) -> dict[str, Any]:
    return {"stacks": [stack.model_dump(by_alias=True) for stack in _state_store(cwd).list()]}


def summarize_context_payload(cwd: str) -> dict[str, str]:
    return {"summary": _state_store(cwd).summary()}


def list_resources_payload(cwd: str) -> dict[str, Any]:
    return {
        "resources": [
            {"server": "docker", "type": "stack", "name": stack.name}
            for stack in _state_store(cwd).list()
        ]
    }


def capabilities_payload() -> dict[str, Any]:
    return {
        "tools": [
            {
                "namespace": "docker",
                "name": "docker.deploy_stack",
                "operation": "plan",
                "risk": "high",
                "mutating": True,
                "confirmation": "plan_review",
                "commit_tool": "docker.commit_action",
                "rollback_tool": "docker.rollback_action",
            },
            {
                "namespace": "docker",
                "name": "docker.commit_action",
                "operation": "commit",
                "risk": "high",
                "mutating": True,
                "confirmation": "none",
                "model_visible": False,
            },
            {
                "namespace": "docker",
                "name": "docker.rollback_action",
                "operation": "rollback",
                "risk": "high",
                "mutating": True,
                "confirmation": "none",
                "model_visible": False,
            },
            *[
                {
                    "namespace": "docker",
                    "name": f"docker.{tool.name}",
                    "risk": "normal",
                    "mutating": False,
                    "confirmation": "none",
                }
                for tool in _READ_ONLY_TOOLS
            ],
            *[
                {
                    "namespace": "docker",
                    "name": f"docker.{tool.name}",
                    "risk": "normal",
                    "mutating": False,
                    "confirmation": "permission",
                }
                for tool in _PERMISSION_TOOLS
            ],
            *[
                {
                    "namespace": "docker",
                    "name": f"docker.{tool.name}",
                    "risk": "high",
                    "mutating": False,
                    "confirmation": "permission",
                }
                for tool in _HIGH_RISK_PERMISSION_TOOLS
            ],
            *[
                {
                    "namespace": "docker",
                    "name": f"docker.{tool.name}",
                    "risk": "high",
                    "mutating": True,
                    "confirmation": "permission",
                }
                for tool in _MUTATING_TOOLS
            ],
        ],
        "commands": [
            {
                "pattern": r"^destroy all stacks$",
                "tool": "docker.destroy_all_stacks",
                "confirmation": "typed",
                "args": {},
                "phrase_template": "DESTROY ALL",
                "reason_template": "This will destroy all Docker stacks.",
            },
            {
                "pattern": r"^destroy (?P<stack_name>\S+) with volumes$",
                "tool": "docker.destroy_stack",
                "confirmation": "typed",
                "args": {"stack_name": "$stack_name", "remove_volumes": True},
                "phrase_template": "DESTROY {stack_name}",
                "reason_template": "This will destroy {stack_name} and delete its volumes.",
            },
            {
                "pattern": r"^destroy (?P<stack_name>\S+)$",
                "tool": "docker.destroy_stack",
                "confirmation": "permission",
                "args": {"stack_name": "$stack_name"},
            },
            {
                "pattern": r"^stop (?P<stack_name>\S+)(?: services? (?P<services>.+))?$",
                "tool": "docker.stop_stack",
                "confirmation": "permission",
                "args": {"stack_name": "$stack_name"},
                "split_args": {"services": "services"},
            },
        ],
        "context": {
            "summarize_tool": "docker.summarize_context",
            "list_resources_tool": "docker.list_resources",
        },
        "instructions": DOCKER_INSTRUCTIONS,
    }


def pending_confirmation_stub(
    *,
    cwd: str,
    session_id: str,
    tool: str,
    ttl_seconds: int = _PENDING_TTL_SECONDS,
) -> dict[str, Any]:
    action = PendingAction(
        id=str(uuid4()),
        session_id=session_id,
        cwd=cwd,
        tool=tool,
        kind="plan_review",
        hash="stub",
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        payload={
            "title": "Review Docker action",
            "summary": "Pending confirmation stub.",
            "artifacts": [
                {
                    "kind": "manifest",
                    "label": "Compose YAML",
                    "language": "yaml",
                    "content": "services: {}",
                },
                {
                    "kind": "diff",
                    "label": "Stack diff",
                    "content": {"stackName": "stub", "status": "missing", "serviceDiffs": []},
                },
            ],
            "auto_generated_secrets": [],
            "config_files": [],
        },
    )
    return _pending_store(cwd).add(action).response_payload()


async def _finalize_plan_result(
    *,
    ctx: ToolContext,
    result: PlanStackResultOk | dict[str, Any],
    progress: list[str],
    draft: StackDraft,
    session_id: str,
    cwd: str,
    provider_name: str,
    model: str | None,
    ttl_seconds: int = _PENDING_TTL_SECONDS,
) -> dict[str, Any]:
    if isinstance(result, dict):
        return {**result, "progress": progress}
    plan_result = result
    history_details: dict[str, Any] = {"hash": plan_result.hash}
    if plan_result.preflight_details is not None:
        history_details["validation"] = plan_result.preflight_details
    ctx.state_store.append_history(
        HistoryEvent(
            ts=datetime.now(UTC).isoformat(),
            session_id=session_id or "unknown",
            stack_name=draft.stack_name,
            action="plan",
            details=history_details,
        )
    )
    action = PendingAction(
        id=str(uuid4()),
        session_id=session_id,
        cwd=cwd,
        tool="docker.deploy_stack",
        kind="plan_review",
        hash=plan_result.hash,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        payload=_plan_confirm_payload(plan_result, draft, ctx),
        private_payload={
            "draft": draft.model_dump(by_alias=True, exclude_none=True),
            "stack_name": draft.stack_name,
            "compose_yaml": plan_result.compose_yaml,
            "config_files": plan_result.config_files,
            "secret_files": plan_result.staged_secret_files,
            "scale_overrides": plan_result.scale_overrides,
            "provider_name": provider_name,
            "model": model,
        },
    )
    response = _pending_store(cwd).add(action).response_payload()
    response["progress"] = progress
    return response


async def deploy_stack_payload(
    *,
    cwd: str,
    session_id: str,
    provider_name: str = "mcp",
    model: str | None = None,
    ttl_seconds: int = _PENDING_TTL_SECONDS,
    **kwargs: Any,
) -> dict[str, Any]:
    draft = StackDraft.model_validate(kwargs)
    ctx, result, progress = await _plan_deploy(
        cwd=cwd,
        session_id=session_id,
        provider_name=provider_name,
        model=model,
        draft=draft,
    )
    return await _finalize_plan_result(
        ctx=ctx,
        result=result,
        progress=progress,
        draft=draft,
        session_id=session_id,
        cwd=cwd,
        provider_name=provider_name,
        model=model,
        ttl_seconds=ttl_seconds,
    )


async def _run_core_tool_payload(
    tool: Any,
    *,
    cwd: str,
    session_id: str,
    provider_name: str = "mcp",
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    ctx = _tool_context(
        cwd=cwd,
        session_id=session_id,
        provider_name=provider_name,
        model=model,
    )
    parsed = tool.input_schema.model_validate(kwargs)
    result, progress = await _drain_tool(tool, parsed, ctx)
    return {"status": "ok", "result": _jsonable(result), "progress": progress}


async def _approve_deploy(action: PendingAction) -> dict[str, Any]:
    private = action.private_payload
    draft = private.get("draft")
    if isinstance(draft, dict):
        draft = StackDraft.model_validate(draft)
    if not isinstance(draft, StackDraft):
        return {"status": "ok", "result": f"confirmed {action.tool}"}
    provider_name = str(private.get("provider_name") or "mcp")
    model = private.get("model") if isinstance(private.get("model"), str) else None
    ctx, revalidated, progress = await _plan_deploy(
        cwd=action.cwd,
        session_id=action.session_id,
        provider_name=provider_name,
        model=model,
        draft=draft,
    )
    if isinstance(revalidated, dict):
        return {**revalidated, "progress": progress}
    if revalidated.hash != action.hash:
        return {
            "status": "error",
            "result": "Pending deploy rejected: plan hash changed during revalidation.",
        }
    events: list[Any] = []
    apply_result = await run_apply_transaction(
        ApplyWithRollbackParams(
            stack_name=str(private["stack_name"]),
            desired_yaml=str(private["compose_yaml"]),
            config_files=list(private.get("config_files") or []),
            secret_files=list(private.get("secret_files") or []),
            ctx=ctx,
            emit=events.append,
            scale_overrides=private.get("scale_overrides") or None,
        )
    )
    if apply_result.rollback is not None:
        _ROLLBACKS[apply_result.rollback.id] = apply_result.rollback
        return {
            "status": "error",
            "result": apply_result.result_message,
            "ok": False,
            "rollback_action": {
                "id": apply_result.rollback.id,
                "tool": "docker.rollback_action",
            },
            "events": [_jsonable(event) for event in events],
        }
    return {
        "status": "ok" if apply_result.ok else "error",
        "result": apply_result.result_message,
        "ok": apply_result.ok,
        "events": [_jsonable(event) for event in events],
    }


async def commit_action_payload(
    *,
    pending_action_id: str,
    session_id: str,
    cwd: str,
    decision: Literal["approve", "deny"],
    typed_phrase: str | None = None,
    secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    del typed_phrase, secrets
    try:
        action = _pending_store(cwd).consume(
            pending_action_id,
            session_id=session_id,
            cwd=cwd,
        )
    except TimeoutError:
        return {
            "status": "error",
            "result": (
                "This plan preview expired before it was approved. "
                "Re-run the deployment to generate a fresh plan, then approve it."
            ),
        }
    except KeyError:
        return {
            "status": "error",
            "result": (
                "No matching pending action was found for this approval. "
                "It may already have been committed or cancelled. "
                "Re-run the deployment if you still want to proceed."
            ),
        }
    except PermissionError:
        return {
            "status": "error",
            "result": (
                "This pending action belongs to a different session or working "
                "directory and cannot be committed here."
            ),
        }
    if decision == "deny":
        return {"status": "ok", "result": f"denied {action.tool}"}
    if action.tool == "docker.deploy_stack":
        return await _approve_deploy(action)
    if action.tool == "initialize_project_policy":
        return await _approve_initialize_project_policy(action)
    return {"status": "ok", "result": f"confirmed {action.tool}"}


async def rollback_action_payload(
    *,
    rollback_action_id: str,
    session_id: str,
    cwd: str,
) -> dict[str, Any]:
    transaction = _ROLLBACKS.pop(rollback_action_id)
    ctx = _tool_context(cwd=cwd, session_id=session_id)
    events: list[Any] = []
    result = await run_rollback_transaction(transaction, ctx=ctx, emit=events.append)
    rollback_ok = (
        bool(getattr(result, "ok", False)) or "rollback succeeded" in result.result_message
    )
    return {
        "status": "ok" if rollback_ok else "error",
        "result": result.result_message,
        "ok": rollback_ok,
        "events": [_jsonable(event) for event in events],
    }


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as err:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "docker-mcp-server requires the mcp package. Install dev dependencies first."
        ) from err

    mcp = FastMCP("docker-mcp-server")

    @mcp.tool(name="docker.capabilities")
    def docker_capabilities() -> dict[str, Any]:
        """Return Docker plugin metadata used by the generic core router."""

        return capabilities_payload()

    @mcp.tool(name="docker.validate_spec")
    async def docker_validate_spec(
        cwd: str,
        session_id: str,
        stackName: str,
        intent: str,
        services: list[dict[str, Any]],
        networkName: str | None = None,
        networks: list[dict[str, Any]] | None = None,
        volumes: list[dict[str, Any]] | None = None,
        configFiles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Validate a Docker stack draft without applying it."""

        return await _run_core_tool_payload(
            validate_spec,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
            intent=intent,
            services=services,
            **({"networkName": networkName} if networkName is not None else {}),
            **({"networks": networks} if networks is not None else {}),
            **({"volumes": volumes} if volumes is not None else {}),
            **({"configFiles": configFiles} if configFiles is not None else {}),
        )

    @mcp.tool(name="docker.resolve_dependency")
    async def docker_resolve_dependency(
        cwd: str,
        session_id: str,
        services: list[dict[str, Any]],
        stackName: str | None = None,
        intent: str | None = None,
        networks: list[dict[str, Any]] | None = None,
        volumes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Validate service dependency order for a Docker stack draft."""

        return await _run_core_tool_payload(
            resolve_dependency,
            cwd=cwd,
            session_id=session_id,
            services=services,
            **({"stackName": stackName} if stackName is not None else {}),
            **({"intent": intent} if intent is not None else {}),
            **({"networks": networks} if networks is not None else {}),
            **({"volumes": volumes} if volumes is not None else {}),
        )

    @mcp.tool(name="docker.list_stacks")
    def docker_list_stacks(cwd: str) -> dict[str, Any]:
        """List Docker stacks from the existing docker-agent state store."""

        return list_stacks_payload(cwd)

    @mcp.tool(name="docker.inspect_drift")
    async def docker_inspect_drift(
        cwd: str,
        session_id: str,
        stackName: str,
    ) -> dict[str, Any]:
        """Compare desired stack state with live Docker resources."""

        return await _run_core_tool_payload(
            inspect_drift,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
        )

    @mcp.tool(name="docker.get_stack_status")
    async def docker_get_stack_status(
        cwd: str,
        session_id: str,
        stackName: str,
        tailLines: int | None = None,
    ) -> dict[str, Any]:
        """Return compose ps rows and a bounded log tail for one stack."""

        return await _run_core_tool_payload(
            get_stack_status,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
            **({"tailLines": tailLines} if tailLines is not None else {}),
        )

    @mcp.tool(name="docker.get_logs")
    async def docker_get_logs(
        cwd: str,
        session_id: str,
        stackName: str,
        service: str | None = None,
        tailLines: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded, redacted log snapshot for one stack."""

        return await _run_core_tool_payload(
            get_logs,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
            **({"service": service} if service is not None else {}),
            **({"tailLines": tailLines} if tailLines is not None else {}),
            **({"since": since} if since is not None else {}),
        )

    @mcp.tool(name="docker.get_health")
    async def docker_get_health(
        cwd: str,
        session_id: str,
        stackName: str,
    ) -> dict[str, Any]:
        """Return per-container status and health metrics for one stack."""

        return await _run_core_tool_payload(
            get_health,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
        )

    @mcp.tool(name="docker.exec_docker")
    async def docker_exec_docker(
        cwd: str,
        session_id: str,
        args: list[str],
    ) -> dict[str, Any]:
        """Run a read-only docker command through the existing whitelist."""

        return await _run_core_tool_payload(
            exec_docker,
            cwd=cwd,
            session_id=session_id,
            args=args,
        )

    @mcp.tool(name="docker.summarize_context")
    def docker_summarize_context(cwd: str) -> dict[str, str]:
        """Summarize Docker state for the core system prompt."""

        return summarize_context_payload(cwd)

    @mcp.tool(name="docker.list_resources")
    def docker_list_resources(cwd: str) -> dict[str, Any]:
        """List Docker resources using the generic context contract."""

        return list_resources_payload(cwd)

    @mcp.tool(name="docker.deploy_stack")
    async def docker_deploy_stack(
        cwd: str,
        session_id: str,
        stackName: str,
        intent: str,
        services: list[dict[str, Any]],
        networkName: str | None = None,
        networks: list[dict[str, Any]] | None = None,
        volumes: list[dict[str, Any]] | None = None,
        configFiles: dict[str, str] | None = None,
        provider_name: str = "mcp",
        model: str | None = None,
    ) -> dict[str, Any]:
        """Plan a Docker stack and return a PendingAction for user confirmation."""

        return await deploy_stack_payload(
            cwd=cwd,
            session_id=session_id,
            provider_name=provider_name,
            model=model,
            stackName=stackName,
            intent=intent,
            services=services,
            **({"networkName": networkName} if networkName is not None else {}),
            **({"networks": networks} if networks is not None else {}),
            **({"volumes": volumes} if volumes is not None else {}),
            **({"configFiles": configFiles} if configFiles is not None else {}),
        )

    @mcp.tool(name="docker.commit_action")
    async def docker_commit_action(
        pending_action_id: str,
        session_id: str,
        cwd: str,
        decision: Literal["approve", "deny"],
        typed_phrase: str | None = None,
        secrets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Commit an approved pending Docker action."""

        return await commit_action_payload(
            pending_action_id=pending_action_id,
            session_id=session_id,
            cwd=cwd,
            decision=decision,
            typed_phrase=typed_phrase,
            secrets=secrets,
        )

    @mcp.tool(name="docker.rollback_action")
    async def docker_rollback_action(
        rollback_action_id: str,
        session_id: str,
        cwd: str,
    ) -> dict[str, Any]:
        """Execute a rollback transaction produced by docker.commit_action."""

        return await rollback_action_payload(
            rollback_action_id=rollback_action_id,
            session_id=session_id,
            cwd=cwd,
        )

    @mcp.tool(name="docker.destroy_stack")
    async def docker_destroy_stack(
        cwd: str,
        session_id: str,
        stack_name: str,
        remove_volumes: bool | None = None,
    ) -> dict[str, Any]:
        """Destroy one managed stack."""

        return await _run_core_tool_payload(
            destroy_stack,
            cwd=cwd,
            session_id=session_id,
            stack_name=stack_name,
            remove_volumes=remove_volumes,
        )

    @mcp.tool(name="docker.destroy_all_stacks")
    async def docker_destroy_all_stacks(cwd: str, session_id: str) -> dict[str, Any]:
        """Destroy all managed stacks."""

        return await _run_core_tool_payload(
            destroy_all_stacks,
            cwd=cwd,
            session_id=session_id,
        )

    @mcp.tool(name="docker.stop_stack")
    async def docker_stop_stack(
        cwd: str,
        session_id: str,
        stack_name: str,
        services: list[str] | None = None,
    ) -> dict[str, Any]:
        """Stop one managed stack or selected services."""

        return await _run_core_tool_payload(
            stop_stack,
            cwd=cwd,
            session_id=session_id,
            stack_name=stack_name,
            services=services,
        )

    @mcp.tool(name="docker.remove_container")
    async def docker_remove_container(
        cwd: str,
        session_id: str,
        containers: list[str],
        force: bool = True,
        stopOnly: bool = False,
    ) -> dict[str, Any]:
        """Stop or remove exact orphan container names/IDs."""

        return await _run_core_tool_payload(
            remove_container,
            cwd=cwd,
            session_id=session_id,
            containers=containers,
            force=force,
            stopOnly=stopOnly,
        )

    @mcp.tool(name="docker.remediate_drift")
    async def docker_remediate_drift(
        cwd: str,
        session_id: str,
        stackName: str,
    ) -> dict[str, Any]:
        """Return desired state for drift remediation; caller confirms any apply."""

        return await _run_core_tool_payload(
            remediate_drift,
            cwd=cwd,
            session_id=session_id,
            stackName=stackName,
        )

    return mcp


def main() -> None:
    build_server().run()


__all__ = [
    "build_server",
    "capabilities_payload",
    "deploy_stack_payload",
    "list_resources_payload",
    "list_stacks_payload",
    "main",
    "pending_confirmation_stub",
    "summarize_context_payload",
]


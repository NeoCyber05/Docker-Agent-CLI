"""Plan review node: plan_stack, policy gate, interrupt confirm, apply.

Parity: ``src/backend/langgraph/nodes/planReviewNode.ts``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from docker_agent.backend.langgraph.nodes.apply_with_rollback import (
    ApplyWithRollbackParams,
    run_apply_with_rollback,
)
from docker_agent.backend.langgraph.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.query import format_plan_blocker
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.tool import ToolDone
from docker_agent.tools.plan_stack import PlanStackResultOk, plan_stack
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.tools.shared.spec_schemas import StackDraft
from docker_agent.types.events import ToolCall, ToolProgress, ToolResult
from docker_agent.types.message import ToolResultMessage
from docker_agent.types.permissions import permission_kind


@dataclass
class PlanReviewNodeDeps:
    ctx: Any
    policy_engine: PolicyEngine
    emit: Callable[[Any], None]


def _block_type(block: Any) -> str | None:
    return getattr(block, "type", None)


def _tool_result(tool_use_id: str, content: str, *, is_error: bool) -> ToolResultMessage:
    return ToolResultMessage(
        role="tool",
        toolUseId=tool_use_id,
        content=content,
        isError=is_error,
    )


async def _request_secrets_and_patch(
    service: str,
    keys: list[str],
    ctx: Any,
    current_input: StackDraft,
) -> dict[str, Any] | None:
    resp = await ctx.request_secrets_input(service, keys, "missing required env")
    if permission_kind(resp) != "secrets_input_values":
        return None
    secrets_dir = Path(ctx.cwd) / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    file_path = secrets_dir / f"{current_input.stack_name}-{service}.env"
    values = resp.get("values", {}) if isinstance(resp, dict) else resp.values
    lines = "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
    file_path.write_text(lines, encoding="utf-8")
    os.chmod(file_path, 0o600)
    for svc in current_input.services:
        if svc.name == service:
            if svc.environment is None:
                svc.environment = {}
            svc.environment.update(values)
            break
    return {"patched_input": current_input}


async def _run_plan_stack(
    input_data: StackDraft,
    ctx: Any,
    emit: Callable[[Any], None],
) -> Any:
    emit(ToolCall(name=plan_stack.name, input=input_data))
    gen = plan_stack.call(input_data, ctx)
    result: Any = None
    async for item in gen:
        if isinstance(item, ToolDone):
            result = item.result
        else:
            emit(ToolProgress(msg=item.msg))
    emit(ToolResult(name=plan_stack.name, output=result))
    return result


async def plan_review_node(deps: PlanReviewNodeDeps, state: AgentState) -> dict[str, Any]:
    last = state.messages[-1] if state.messages else None
    if not last or last.role != "assistant":
        return {}

    plan_call = next(
        (
            b
            for b in last.content
            if _block_type(b) == "tool_use" and getattr(b, "name", None) == "plan_stack"
        ),
        None,
    )
    if plan_call is None or not getattr(plan_call, "id", None):
        return {}

    tool_use_id = str(getattr(plan_call, "id", ""))
    tool_input = getattr(plan_call, "input", {})

    try:
        parsed_input = plan_stack.input_schema.model_validate(tool_input)
    except Exception as err:
        msg = f"plan_stack validation failed: {err}"
        return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}

    plan_result: PlanStackResultOk | None = None

    while True:
        result = await _run_plan_stack(parsed_input, deps.ctx, deps.emit)

        if result.blocked:
            if result.reason == "missing_config_file":
                paths = ", ".join(result.missing_files or [])
                msg = (
                    f"Missing content for bind-mounted config file(s): {paths}. "
                    "Re-run plan_stack including each path in the configFiles map "
                    "with its full content."
                )
                return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}
            if result.reason in (
                "invalid_spec",
                "invalid_dependency",
                "port_conflict",
                "resource_limit",
                "db_port_exposed",
                "unsafe_volume",
                "undeclared_network",
                "invalid_yaml",
            ):
                msg = format_plan_blocker(result)
                return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}
            injected = result.missing_by_service or {}
            patched: StackDraft | None = parsed_input
            for service, keys in injected.items():
                resp = await _request_secrets_and_patch(
                    service, keys, deps.ctx, patched or parsed_input
                )
                if resp is None:
                    return {
                        "messages": [
                            _tool_result(
                                tool_use_id,
                                "User cancelled secrets input.",
                                is_error=False,
                            )
                        ]
                    }
                patched = resp["patched_input"]
            if patched is not None:
                parsed_input = patched
            continue

        plan_result = result
        break

    assert plan_result is not None

    secret_keys = collect_secret_keys(
        parsed_input.stack_name,
        SecretKeysContext(cwd=deps.ctx.cwd, state_store=deps.ctx.state_store),
    )

    violations = deps.policy_engine.evaluate(plan_result.compose_yaml)
    deny_violations = [v for v in violations if v.severity == "deny"]
    if deny_violations:
        msgs = "\n".join(f"[{v.service}] {v.rule}: {v.message}" for v in deny_violations)
        msg = f"Policy violation(s) detected. Deployment is blocked:\n{msgs}"
        return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}

    confirm_payload: dict[str, Any] = {
        "compose_yaml": plan_result.compose_yaml,
        "diff": plan_result.diff,
        "hash": plan_result.hash,
    }
    if plan_result.auto_generated_secrets:
        confirm_payload["auto_generated_secrets"] = [
            {"service": s.service, "keys": s.keys}
            for s in plan_result.auto_generated_secrets
        ]
    if plan_result.config_files:
        confirm_payload["config_files"] = [
            {
                "path": f.path,
                "content": "\n".join(
                    scrub_line(line, secret_keys) for line in f.content.split("\n")
                ),
                "bytes": f.bytes,
            }
            for f in plan_result.config_files
        ]

    confirm = interrupt(confirm_payload)
    if permission_kind(confirm) != "approve":
        return {
            "messages": [_tool_result(tool_use_id, "plan denied by user", is_error=False)],
            "aborted": True,
        }

    apply_params = ApplyWithRollbackParams(
        stack_name=parsed_input.stack_name,
        desired_yaml=plan_result.compose_yaml,
        config_files=plan_result.config_files,
        ctx=deps.ctx,
        emit=deps.emit,
        scale_overrides=(
            plan_result.scale_overrides if plan_result.scale_overrides else None
        ),
    )
    apply_result = await run_apply_with_rollback(apply_params)

    return {
        "messages": [
            _tool_result(
                tool_use_id,
                apply_result.result_message,
                is_error=not apply_result.ok,
            )
        ]
    }
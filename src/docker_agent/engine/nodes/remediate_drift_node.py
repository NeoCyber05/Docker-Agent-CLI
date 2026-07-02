"""Remediate drift node: detect drift, policy gate, interrupt confirm, apply.

Parity: ``src/backend/langgraph/nodes/remediateDriftNode.ts``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from docker_agent.engine.nodes.apply_with_rollback import (
    ApplyWithRollbackParams,
    run_apply_with_rollback,
)
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.state.state_store import HistoryEvent
from docker_agent.tools.base import ToolDone
from docker_agent.tools.remediate_drift import remediate_drift
from docker_agent.types.events import ToolCall, ToolProgress, ToolResult
from docker_agent.types.message import ToolResultMessage
from docker_agent.types.permissions import permission_kind


@dataclass
class RemediateDriftNodeDeps:
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


async def remediate_drift_node(
    deps: RemediateDriftNodeDeps, state: AgentState
) -> dict[str, Any]:
    last = state.messages[-1] if state.messages else None
    if not last or last.role != "assistant":
        return {}

    call = next(
        (
            b
            for b in last.content
            if _block_type(b) == "tool_use" and getattr(b, "name", None) == "remediate_drift"
        ),
        None,
    )
    if call is None or not getattr(call, "id", None):
        return {}

    tool_use_id = str(getattr(call, "id", ""))
    tool_input = getattr(call, "input", {})

    try:
        parsed = remediate_drift.input_schema.model_validate(tool_input)
    except Exception as err:
        msg = f"remediate_drift validation failed: {err}"
        return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}

    deps.emit(ToolCall(name=remediate_drift.name, input=parsed))
    gen = remediate_drift.call(parsed, deps.ctx)
    result: Any = None
    async for item in gen:
        if isinstance(item, ToolDone):
            result = item.result
        else:
            deps.emit(ToolProgress(msg=item.msg))
    deps.emit(ToolResult(name=remediate_drift.name, output=result))

    if not result.remediable:
        msg = f"No remediation needed: {result.reason or 'unknown'}"
        return {"messages": [_tool_result(tool_use_id, msg, is_error=False)]}

    violations = deps.policy_engine.evaluate(result.desired_yaml)
    if violations:
        msgs = "\n".join(f"[{v.service}] {v.rule}: {v.message}" for v in violations)
        msg = f"Policy violation(s) detected. Remediation is blocked:\n{msgs}"
        return {"messages": [_tool_result(tool_use_id, msg, is_error=True)]}

    confirm = interrupt(
        {
            "compose_yaml": result.desired_yaml,
            "diff": result.diff,
        }
    )
    if permission_kind(confirm) != "approve":
        return {
            "messages": [_tool_result(tool_use_id, "User declined remediation.", is_error=False)],
            "aborted": True,
        }

    apply_result = await run_apply_with_rollback(
        ApplyWithRollbackParams(
            stack_name=parsed.stack_name,
            desired_yaml=result.desired_yaml,
            config_files=[],
            ctx=deps.ctx,
            emit=deps.emit,
        )
    )

    result_message = apply_result.result_message
    fully_clean = apply_result.ok
    if result.diff.status == "extra":
        orphans = [
            d.service
            for d in result.diff.service_diffs
            if d.desired is None and d.actual is not None
        ]
        if orphans:
            fully_clean = False
            result_message += (
                f" Remediation not fully clean: {len(orphans)} orphan service(s) "
                f"remain ({', '.join(orphans)}). Automatic orphan removal is out of "
                "scope (future option)."
            )

    deps.ctx.state_store.append_history(
        HistoryEvent(
            ts=datetime.now(UTC).isoformat(),
            session_id=deps.ctx.session_id or "unknown",
            stack_name=parsed.stack_name,
            action="remediate",
            details={
                "status": result.diff.status,
                "ok": apply_result.ok,
                "fullyClean": fully_clean,
            },
        )
    )

    return {
        "messages": [
            _tool_result(
                tool_use_id,
                result_message,
                is_error=not apply_result.ok,
            )
        ]
    }
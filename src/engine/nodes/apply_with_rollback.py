"""Apply a desired stack YAML with rollback on failure.

Parity: ``src/backend/langgraph/nodes/applyWithRollback.ts``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from src.engine.adapters.tool_adapter import run_tool
from src.state.rollback import capture_known_good, plan_rollback
from src.state.state_store import HistoryEvent
from src.tools.apply_stack import apply_stack
from src.tools.destroy_stack import destroy_stack
from src.tools.shared.config_files import (
    StagedConfigFile,
    restore_config_files,
    snapshot_config_files,
    write_config_files,
)
from src.types.events import (
    RollbackResult,
    RollbackStarted,
    ToolCall,
    ToolProgress,
    ToolResult,
)


@dataclass
class ApplyWithRollbackParams:
    stack_name: str
    desired_yaml: str
    config_files: list[StagedConfigFile]
    ctx: Any
    emit: Callable[[Any], None]
    scale_overrides: dict[str, int] | None = None


@dataclass
class ApplyWithRollbackResult:
    ok: bool
    result_message: str


async def _run_apply_tool(
    tool: Any,
    input_data: Any,
    ctx: Any,
    emit: Callable[[Any], None],
) -> Any:
    emit(ToolCall(name=tool.name, input=input_data))
    run = await run_tool(tool, input_data, ctx)
    for p in run.progress:
        emit(ToolProgress(msg=p.msg))
    emit(ToolResult(name=tool.name, output=run.output))
    return run.output


async def run_apply_with_rollback(params: ApplyWithRollbackParams) -> ApplyWithRollbackResult:
    stack_name = params.stack_name
    ctx = params.ctx
    emit = params.emit

    known = capture_known_good(stack_name, {"state_store": ctx.state_store})
    snapshots = snapshot_config_files(ctx.cwd, params.config_files)
    try:
        write_config_files(ctx.cwd, params.config_files)
    except Exception as err:
        restore_config_files(snapshots)
        return ApplyWithRollbackResult(
            ok=False, result_message=f"failed to write config files: {err}"
        )

    apply_input = apply_stack.input_schema.model_validate(
        {
            "stack_name": stack_name,
            "compose_yaml": params.desired_yaml,
            **(
                {"scale_overrides": params.scale_overrides}
                if params.scale_overrides
                else {}
            ),
        }
    )
    apply_result = await _run_apply_tool(apply_stack, apply_input, ctx, emit)

    if apply_result.ok:
        return ApplyWithRollbackResult(ok=True, result_message="Stack applied.")

    reason = "unhealthy" if apply_result.healthy is False else "apply_failed"
    logs_tail = f"\nRecent logs:\n{apply_result.error_output}" if apply_result.error_output else ""
    detail = (
        f"unhealthy: {', '.join(apply_result.unhealthy_services or [])}{logs_tail}"
        if reason == "unhealthy"
        else f"exit {apply_result.exit_code}: {apply_result.error_output or 'unknown'}"
    )

    emit(
        RollbackStarted(
            stackName=stack_name,
            reason=reason,
            detail=detail,
            runningServices=apply_result.running_services,
        )
    )

    plan = plan_rollback(known, stack_name)
    restored: Literal["previous", "removed", "none"] = "none"
    rollback_ok = True

    try:
        if plan.strategy == "restore_previous":
            restore_input = apply_stack.input_schema.model_validate(
                {"stack_name": stack_name, "compose_yaml": plan.compose_yaml}
            )
            restore = await _run_apply_tool(apply_stack, restore_input, ctx, emit)
            rollback_ok = restore.ok
            restored = "previous"
        elif plan.strategy == "teardown_partial":
            down_input = destroy_stack.input_schema.model_validate({"stack_name": stack_name})
            down = await _run_apply_tool(destroy_stack, down_input, ctx, emit)
            rollback_ok = down.ok
            restored = "removed"
        else:
            rollback_ok = False
            restored = "none"
    except Exception:
        rollback_ok = False

    restore_config_files(snapshots)

    ctx.state_store.append_history(
        HistoryEvent(
            ts=datetime.now(UTC).isoformat(),
            session_id=ctx.session_id or "unknown",
            stack_name=stack_name,
            action="rollback",
            details={"reason": reason, "restored": restored, "rollback_ok": rollback_ok},
        )
    )

    emit(
        RollbackResult(
            stackName=stack_name,
            ok=rollback_ok,
            restored=restored,
            **({"detail": "manual intervention may be required"} if not rollback_ok else {}),
        )
    )

    status = "succeeded" if rollback_ok else "FAILED"
    return ApplyWithRollbackResult(
        ok=False,
        result_message=f"apply failed ({detail}); rollback {status} ({restored}).",
    )
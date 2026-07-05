"""Apply Docker stacks with rollback-compatible transaction helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from docker_agent.state.rollback import capture_known_good, plan_rollback
from docker_agent.state.state_store import HistoryEvent
from docker_agent.tools.apply_stack import apply_stack
from docker_agent.tools.base import ToolDone
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.tools.shared.config_files import (
    StagedConfigFile,
    restore_config_files,
    snapshot_config_files,
    write_config_files,
)
from docker_agent.tools.shared.secret_staging import (
    StagedSecretFile,
    restore_secret_files,
    snapshot_secret_files,
    write_secret_files,
)
from docker_agent.types.events import (
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
    secret_files: list[StagedSecretFile] | None = None


@dataclass
class ApplyWithRollbackResult:
    ok: bool
    result_message: str


@dataclass
class RollbackTransaction:
    id: str
    stack_name: str
    known: Any
    reason: Literal["apply_failed", "unhealthy"]
    detail: str
    config_snapshots: list[Any]
    secret_snapshots: list[Any]
    running_services: list[str] | None = None


@dataclass
class ApplyTransactionResult:
    ok: bool
    result_message: str
    rollback: RollbackTransaction | None = None


def _rollback_start_detail(detail: str) -> str:
    clean = detail.strip() or "unknown"
    return f"Deploy failed: {clean}. Starting rollback..."


async def _run_apply_tool(
    tool: Any,
    input_data: Any,
    ctx: Any,
    emit: Callable[[Any], None],
) -> Any:
    emit(ToolCall(name=tool.name, input=input_data))
    output: Any = None
    async for item in tool.call(input_data, ctx):
        if isinstance(item, ToolDone):
            output = item.result
        else:
            emit(ToolProgress(msg=item.msg))
    emit(ToolResult(name=tool.name, output=output))
    return output


def _failure_detail(apply_result: Any, reason: Literal["apply_failed", "unhealthy"]) -> str:
    logs_tail = f"\nRecent logs:\n{apply_result.error_output}" if apply_result.error_output else ""
    if reason == "unhealthy":
        return f"unhealthy: {', '.join(apply_result.unhealthy_services or [])}{logs_tail}"
    return f"exit {apply_result.exit_code}: {apply_result.error_output or 'unknown'}"


async def run_apply_transaction(params: ApplyWithRollbackParams) -> ApplyTransactionResult:
    stack_name = params.stack_name
    ctx = params.ctx
    emit = params.emit

    known = capture_known_good(stack_name, {"state_store": ctx.state_store})
    config_snapshots = snapshot_config_files(ctx.cwd, params.config_files)
    secret_files = params.secret_files or []
    secret_snapshots = snapshot_secret_files(secret_files)
    try:
        write_config_files(ctx.cwd, params.config_files)
        write_secret_files(secret_files)
    except Exception as err:
        restore_config_files(config_snapshots)
        restore_secret_files(secret_snapshots)
        return ApplyTransactionResult(
            ok=False,
            result_message=f"failed to write staged files: {err}",
            rollback=None,
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
        if apply_result.warnings:
            warning_lines = "\n".join(f"- {item}" for item in apply_result.warnings)
            return ApplyTransactionResult(
                ok=True,
                result_message=(
                    "Stack applied. CANH BAO: phat hien dau hieu loi trong log hoac "
                    f"kiem tra HTTP khong ket luan duoc:\n{warning_lines}"
                ),
            )
        return ApplyTransactionResult(ok=True, result_message="Stack applied.")

    reason: Literal["apply_failed", "unhealthy"] = (
        "unhealthy" if apply_result.healthy is False else "apply_failed"
    )
    detail = _failure_detail(apply_result, reason)
    rollback = RollbackTransaction(
        id=str(uuid4()),
        stack_name=stack_name,
        known=known,
        reason=reason,
        detail=detail,
        config_snapshots=config_snapshots,
        secret_snapshots=secret_snapshots,
        running_services=apply_result.running_services,
    )
    return ApplyTransactionResult(
        ok=False,
        result_message=f"apply failed ({detail}); rollback required.",
        rollback=rollback,
    )


async def run_rollback_transaction(
    transaction: RollbackTransaction,
    *,
    ctx: Any,
    emit: Callable[[Any], None],
) -> ApplyWithRollbackResult:
    stack_name = transaction.stack_name
    reason = transaction.reason
    detail = transaction.detail
    emit(
        RollbackStarted(
            stackName=stack_name,
            reason=reason,
            detail=_rollback_start_detail(detail),
            runningServices=transaction.running_services,
        )
    )

    plan = plan_rollback(transaction.known, stack_name)
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
    finally:
        restore_config_files(transaction.config_snapshots)
        restore_secret_files(transaction.secret_snapshots)

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


async def run_apply_with_rollback(params: ApplyWithRollbackParams) -> ApplyWithRollbackResult:
    apply_result = await run_apply_transaction(params)
    if apply_result.ok or apply_result.rollback is None:
        return ApplyWithRollbackResult(
            ok=apply_result.ok,
            result_message=apply_result.result_message,
        )
    return await run_rollback_transaction(
        apply_result.rollback,
        ctx=params.ctx,
        emit=params.emit,
    )


__all__ = [
    "ApplyTransactionResult",
    "ApplyWithRollbackParams",
    "ApplyWithRollbackResult",
    "RollbackTransaction",
    "run_apply_transaction",
    "run_apply_with_rollback",
    "run_rollback_transaction",
]

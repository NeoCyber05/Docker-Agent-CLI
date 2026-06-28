"""Current backend query loop.

Parity: ``src/query.ts``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from docker_agent.config import load_user_config
from docker_agent.context import build_system_prompt
from docker_agent.loop_context import LoopContext
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.services.api.types import CallModelParams, Provider, ToolSchema
from docker_agent.slash_dispatch import is_destroy_all_prompt, parse_direct_destroy_stack
from docker_agent.state.rollback import capture_known_good, plan_rollback
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.state.state_store import HistoryEvent
from docker_agent.tool import Tool, ToolDone, find_tool_by_name
from docker_agent.tool import ToolProgress as ToolProgressMsg
from docker_agent.tools import get_agent_tools
from docker_agent.tools.apply_stack import apply_stack
from docker_agent.tools.destroy_all_stacks import destroy_all_stacks
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.tools.plan_stack import PlanStackResultBlocked, plan_stack  # noqa: F401
from docker_agent.tools.remediate_drift import remediate_drift
from docker_agent.tools.shared.config_files import (
    StagedConfigFile,
    restore_config_files,
    snapshot_config_files,
    write_config_files,
)
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.types.events import (
    AssistantText,
    Error,
    IterationStart,
    LoopEvent,
    RollbackResult,
    RollbackStarted,
    ToolCall,
    ToolProgress,
    ToolResult,
    Usage,
)
from docker_agent.types.message import (
    AssistantBlock,
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)

from docker_agent.iteration_limits import MAX_ITERATIONS, build_graceful_summary


def format_plan_blocker(result: PlanStackResultBlocked) -> str:
    """Format a blocked plan_stack result into a user-facing message."""
    reason = result.reason
    if reason == "invalid_spec":
        issues = result.issues or []
        body = "\n".join(f"- [{i.path}] {i.message}" for i in issues)
        return f"plan_stack blocked: Specification is invalid:\n{body}"
    if reason == "invalid_dependency":
        dep = result.dependency
        lines = ["plan_stack blocked: Invalid dependency order."]
        if dep is not None:
            for m in dep.missing:
                lines.append(
                    f"- Service '{m.service}' depends on missing service '{m.dependency}'."
                )
            for cycle in dep.cycles:
                lines.append(f"- Circular dependency detected: {' -> '.join(cycle)}.")
        return "\n".join(lines)
    if reason == "port_conflict":
        pc = result.port_check
        lines = ["plan_stack blocked: Port conflict detected."]
        if pc is not None:
            for conflict in pc.conflicts:
                source = (
                    "running container"
                    if conflict.source == "running"
                    else "other service"
                )
                lines.append(
                    f"- Port {conflict.host_port}/{conflict.protocol} published by service "
                    f"'{conflict.service}' conflicts with {conflict.conflicts_with} ({source})."
                )
            for inv in pc.invalid:
                lines.append(
                    f"- Service '{inv['service']}' has invalid port mapping "
                    f"'{inv['value']}': {inv['message']}"
                )
            if pc.docker_error:
                lines.append(f"- Docker Engine error: {pc.docker_error['message']}")
        return "\n".join(lines)
    if reason == "missing_config_file":
        paths = result.missing_files or []
        return (
            f"plan_stack blocked: Missing content for config file(s): {', '.join(paths)}."
        )
    if reason == "missing_required_env":
        lines = ["plan_stack blocked: Missing required environment variables."]
        for svc, keys in (result.missing_by_service or {}).items():
            lines.append(f"- Service '{svc}' requires: {', '.join(keys)}")
        return "\n".join(lines)
    if reason == "resource_limit":
        resource_issues = result.resource_issues or []
        body = "\n".join(f"- [{i.path}] {i.message}" for i in resource_issues)
        return f"plan_stack blocked: Resource limit exceeded:\n{body}"
    if reason == "db_port_exposed":
        db_issues = result.db_port_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in db_issues)
        return f"plan_stack blocked: Database port publicly exposed:\n{body}"
    if reason == "unsafe_volume":
        volume_issues = result.volume_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in volume_issues)
        return f"plan_stack blocked: Unsafe volume mount detected:\n{body}"
    if reason == "undeclared_network":
        network_issues = result.network_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in network_issues)
        return f"plan_stack blocked: Undeclared network reference:\n{body}"
    if reason == "invalid_yaml":
        return f"plan_stack blocked: {result.error}"
    return f"plan_stack blocked: {reason}"


@dataclass
class CollectedToolUse:
    id: str
    name: str
    args_partial: str


@dataclass
class ProviderTurnResult:
    text: str = ""
    tool_uses: list[CollectedToolUse] = field(default_factory=list)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"] = "end_turn"


def _provider_event_type(ev: object) -> str:
    if isinstance(ev, dict):
        return str(ev.get("type", ""))
    return str(getattr(ev, "type", ""))


def _provider_event_field(ev: object, name: str, alias: str | None = None) -> Any:
    if isinstance(ev, dict):
        if alias and alias in ev:
            return ev[alias]
        return ev.get(name)
    if alias and hasattr(ev, alias):
        return getattr(ev, alias)
    return getattr(ev, name, None)


def _response_kind(resp: Any) -> str:
    if isinstance(resp, dict):
        return str(resp.get("kind", ""))
    return str(getattr(resp, "kind", ""))


def _finalize_provider_turn(
    turn_out: ProviderTurnResult,
    *,
    text: str,
    tool_uses: list[CollectedToolUse],
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"],
) -> None:
    turn_out.text = text
    turn_out.tool_uses = tool_uses
    turn_out.stop_reason = stop_reason


async def run_provider(
    provider: Provider,
    messages: list[Message],
    ctx: LoopContext,
    model: str | None,
    turn_out: ProviderTurnResult,
) -> AsyncIterator[LoopEvent]:
    tools = get_agent_tools()
    system = build_system_prompt(ctx.state_store.summary())
    params = CallModelParams(
        messages=messages,
        tools=[
            ToolSchema(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in tools
        ],
        system=system,
        model=model,
        signal=ctx.abort_signal,
    )
    text = ""
    tool_uses: list[CollectedToolUse] = []
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"] = "end_turn"

    async for ev in provider.stream(params):
        if ctx.abort_signal.is_set():
            _finalize_provider_turn(
                turn_out, text=text, tool_uses=tool_uses, stop_reason="end_turn"
            )
            return
        ev_type = _provider_event_type(ev)
        if ev_type == "text_delta":
            delta = str(_provider_event_field(ev, "text"))
            text += delta
            yield AssistantText(delta=delta)
        elif ev_type == "tool_use_start":
            tool_uses.append(
                CollectedToolUse(
                    id=str(_provider_event_field(ev, "id")),
                    name=str(_provider_event_field(ev, "name")),
                    args_partial="",
                )
            )
        elif ev_type == "tool_use_delta":
            tool_id = str(_provider_event_field(ev, "id"))
            partial = str(
                _provider_event_field(ev, "args_partial_json", "argsPartialJson") or ""
            )
            for use in tool_uses:
                if use.id == tool_id:
                    use.args_partial += partial
        elif ev_type == "tool_use_stop":
            pass
        elif ev_type == "error":
            yield Error(error=_provider_event_field(ev, "error"))
            _finalize_provider_turn(
                turn_out, text=text, tool_uses=tool_uses, stop_reason="end_turn"
            )
            return
        elif ev_type == "message_stop":
            stop_reason = _provider_event_field(ev, "stop_reason", "stopReason") or "end_turn"
            _finalize_provider_turn(
                turn_out, text=text, tool_uses=tool_uses, stop_reason=stop_reason
            )
            return
        elif ev_type == "usage":
            yield Usage(
                inputTokens=int(_provider_event_field(ev, "input_tokens", "inputTokens") or 0),
                outputTokens=int(_provider_event_field(ev, "output_tokens", "outputTokens") or 0),
            )

    _finalize_provider_turn(
        turn_out, text=text, tool_uses=tool_uses, stop_reason=stop_reason
    )


async def run_tool(
    tool: Tool[Any, Any],
    input_data: Any,
    ctx: LoopContext,
) -> AsyncIterator[LoopEvent]:
    yield ToolCall(name=tool.name, input=input_data)
    output: Any = None
    async for item in tool.call(input_data, cast(Any, ctx)):
        if isinstance(item, ToolDone):
            output = item.result
        elif isinstance(item, ToolProgressMsg):
            yield ToolProgress(msg=item.msg)
    yield ToolResult(name=tool.name, output=output)


def assistant_blocks_from_collected(
    text: str,
    tool_uses: list[CollectedToolUse],
) -> list[Any]:
    blocks: list[Any] = []
    if text:
        blocks.append(AssistantBlock.model_validate({"type": "text", "text": text}))
    for tu in tool_uses:
        try:
            input_data = json.loads(tu.args_partial or "{}")
        except json.JSONDecodeError:
            input_data = {}
        blocks.append(
            AssistantBlock.model_validate(
                {"type": "tool_use", "id": tu.id, "name": tu.name, "input": input_data}
            )
        )
    return blocks


async def _drain_tool_stream(
    stream: AsyncIterator[LoopEvent],
) -> tuple[list[LoopEvent], Any]:
    events: list[LoopEvent] = []
    output: Any = None
    async for ev in stream:
        events.append(ev)
        if isinstance(ev, ToolResult):
            output = ev.output
    return events, output


async def apply_with_rollback(
    stack_name: str,
    desired_yaml: str,
    scale_overrides: dict[str, int] | None,
    config_files: list[StagedConfigFile],
    ctx: LoopContext,
) -> tuple[list[LoopEvent], dict[str, Any]]:
    events: list[LoopEvent] = []
    known = capture_known_good(stack_name, {"state_store": ctx.state_store})
    snapshots = snapshot_config_files(ctx.cwd, config_files)
    try:
        write_config_files(ctx.cwd, config_files)
    except OSError as err:
        restore_config_files(snapshots)
        return events, {
            "ok": False,
            "result_message": f"failed to write config files: {err}",
        }

    apply_input = apply_stack.input_schema.model_validate(
        {
            "stack_name": stack_name,
            "compose_yaml": desired_yaml,
            **({"scale_overrides": scale_overrides} if scale_overrides else {}),
        }
    )
    apply_events, apply_result = await _drain_tool_stream(
        run_tool(cast(Tool[Any, Any], apply_stack), apply_input, ctx)
    )
    events.extend(apply_events)

    if apply_result.ok:
        return events, {"ok": True, "result_message": "Stack applied."}

    reason: Literal["apply_failed", "unhealthy"] = (
        "unhealthy" if apply_result.healthy is False else "apply_failed"
    )
    logs_tail = (
        f"\nRecent logs:\n{apply_result.error_output}" if apply_result.error_output else ""
    )
    detail = (
        f"unhealthy: {', '.join(apply_result.unhealthy_services or [])}{logs_tail}"
        if reason == "unhealthy"
        else f"exit {apply_result.exit_code}: {apply_result.error_output or 'unknown'}"
    )

    events.append(
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
            restore_events, restore = await _drain_tool_stream(
                run_tool(cast(Tool[Any, Any], apply_stack), restore_input, ctx)
            )
            events.extend(restore_events)
            rollback_ok = restore.ok
            restored = "previous"
        elif plan.strategy == "teardown_partial":
            down_input = destroy_stack.input_schema.model_validate({"stack_name": stack_name})
            down_events, down = await _drain_tool_stream(
                run_tool(cast(Tool[Any, Any], destroy_stack), down_input, ctx)
            )
            events.extend(down_events)
            rollback_ok = getattr(down, "ok", True)
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

    events.append(
        RollbackResult(
            stackName=stack_name,
            ok=rollback_ok,
            restored=restored,
            **({"detail": "manual intervention may be required"} if not rollback_ok else {}),
        )
    )

    status = "succeeded" if rollback_ok else "FAILED"
    return events, {
        "ok": False,
        "result_message": f"apply failed ({detail}); rollback {status} ({restored}).",
    }


async def request_secrets_and_patch(
    service: str,
    keys: list[str],
    ctx: LoopContext,
    current_input: Any,
) -> Any | None:
    resp = await ctx.request_secrets_input(service, keys, "missing required env")
    if _response_kind(resp) != "secrets_input_values":
        return None
    values = resp.get("values", {}) if isinstance(resp, dict) else resp.values
    secrets_dir = Path(ctx.cwd) / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    stack_name = current_input.stack_name
    env_file = secrets_dir / f"{stack_name}-{service}.env"
    lines = "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
    env_file.write_text(lines, encoding="utf-8")
    os.chmod(env_file, 0o600)
    for svc in current_input.services:
        if svc.name == service:
            if svc.environment is None:
                svc.environment = {}
            svc.environment.update(values)
            break
    return current_input


async def handle_plan_stack_tool_use(
    tu: CollectedToolUse,
    ctx: LoopContext,
    policy_engine: PolicyEngine,
) -> tuple[list[LoopEvent], dict[str, Any]]:
    events: list[LoopEvent] = []
    parsed: Any
    try:
        parsed = plan_stack.input_schema.model_validate(json.loads(tu.args_partial or "{}"))
    except Exception as err:
        return events, {
            "is_error": True,
            "result_message": f"plan_stack validation failed: {err}",
        }

    while True:
        plan_events, plan_result = await _drain_tool_stream(
            run_tool(cast(Tool[Any, Any], plan_stack), parsed, ctx)
        )
        events.extend(plan_events)

        if isinstance(plan_result, PlanStackResultBlocked):
            if plan_result.reason in (
                "invalid_spec",
                "invalid_dependency",
                "port_conflict",
                "resource_limit",
                "db_port_exposed",
                "unsafe_volume",
                "undeclared_network",
                "invalid_yaml",
            ):
                return events, {
                    "is_error": True,
                    "result_message": format_plan_blocker(plan_result),
                }
            if plan_result.reason == "missing_config_file":
                paths = ", ".join(plan_result.missing_files or [])
                return events, {
                    "is_error": True,
                    "result_message": (
                        f"Missing content for bind-mounted config file(s): {paths}. "
                        "Re-run plan_stack including each path in the configFiles map "
                        "with its full content."
                    ),
                }
            for service, keys in (plan_result.missing_by_service or {}).items():
                patched = await request_secrets_and_patch(service, keys, ctx, parsed)
                if patched is None:
                    return events, {
                        "is_error": False,
                        "result_message": "User cancelled secrets input.",
                    }
                parsed = patched
            continue

        secret_keys = collect_secret_keys(
            parsed.stack_name,
            SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store),
        )
        violations = policy_engine.evaluate(plan_result.compose_yaml)
        deny_violations = [v for v in violations if v.severity == "deny"]
        if deny_violations:
            msgs = "\n".join(
                f"[{v.service}] {v.rule}: {v.message}" for v in deny_violations
            )
            return events, {
                "is_error": True,
                "result_message": (
                    f"Policy violation(s) detected. Deployment is blocked:\n{msgs}"
                ),
            }

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
        confirm = await ctx.request_confirm(confirm_payload)
        if _response_kind(confirm) != "approve":
            return events, {
                "is_error": False,
                "result_message": "User declined plan.",
                "user_declined": True,
            }

        scale = plan_result.scale_overrides or None
        if scale is not None and len(scale) == 0:
            scale = None
        apply_events, apply_done = await apply_with_rollback(
            parsed.stack_name,
            plan_result.compose_yaml,
            scale,
            plan_result.config_files,
            ctx,
        )
        events.extend(apply_events)
        return events, {
            "is_error": not apply_done["ok"],
            "result_message": apply_done["result_message"],
        }


async def handle_remediate_drift_tool_use(
    tu: CollectedToolUse,
    ctx: LoopContext,
    policy_engine: PolicyEngine,
) -> tuple[list[LoopEvent], dict[str, Any]]:
    events: list[LoopEvent] = []
    try:
        parsed = remediate_drift.input_schema.model_validate(
            json.loads(tu.args_partial or "{}")
        )
    except Exception as err:
        return events, {
            "is_error": True,
            "result_message": f"remediate_drift validation failed: {err}",
        }

    remediate_events, result = await _drain_tool_stream(
        run_tool(cast(Tool[Any, Any], remediate_drift), parsed, ctx)
    )
    events.extend(remediate_events)

    if not result.remediable:
        return events, {
            "is_error": False,
            "result_message": f"No remediation needed: {result.reason or 'unknown'}",
        }

    violations = policy_engine.evaluate(result.desired_yaml)
    deny_violations = [v for v in violations if v.severity == "deny"]
    if deny_violations:
        msgs = "\n".join(f"[{v.service}] {v.rule}: {v.message}" for v in deny_violations)
        return events, {
            "is_error": True,
            "result_message": (
                f"Policy violation(s) detected. Remediation is blocked:\n{msgs}"
            ),
        }

    confirm = await ctx.request_confirm(
        {"compose_yaml": result.desired_yaml, "diff": result.diff}
    )
    if _response_kind(confirm) != "approve":
        return events, {
            "is_error": False,
            "result_message": "User declined remediation.",
            "user_declined": True,
        }

    apply_events, apply_done = await apply_with_rollback(
        parsed.stack_name, result.desired_yaml, None, [], ctx
    )
    events.extend(apply_events)

    result_message = apply_done["result_message"]
    fully_clean = apply_done["ok"]
    if result.diff.status == "extra":
        orphans = [
            d.service
            for d in result.diff.service_diffs
            if d.desired is None and d.actual is not None
        ]
        if orphans:
            fully_clean = False
            result_message += (
                f" Remediation not fully clean: {len(orphans)} orphan service(s) remain "
                f"({', '.join(orphans)}). Automatic orphan removal is out of scope "
                "(future option)."
            )

    ctx.state_store.append_history(
        HistoryEvent(
            ts=datetime.now(UTC).isoformat(),
            session_id=ctx.session_id or "unknown",
            stack_name=parsed.stack_name,
            action="remediate",
            details={
                "status": result.diff.status,
                "ok": apply_done["ok"],
                "fullyClean": fully_clean,
            },
        )
    )
    return events, {"is_error": not apply_done["ok"], "result_message": result_message}


async def run_direct_destroy_stack(
    stack_name: str,
    remove_volumes: bool,
    ctx: LoopContext,
) -> AsyncIterator[LoopEvent]:
    input_data = destroy_stack.input_schema.model_validate(
        {
            "stack_name": stack_name,
            **({"remove_volumes": True} if remove_volumes else {}),
        }
    )
    if remove_volumes:
        phrase = f"DESTROY {stack_name}"
        typed = await ctx.request_typed_confirm(
            phrase,
            f"This will destroy the stack {stack_name} and delete all its volumes.",
        )
        typed_value = typed.get("value") if isinstance(typed, dict) else typed.value
        if _response_kind(typed) != "typed_confirm_value" or typed_value != phrase:
            yield AssistantText(delta="destroy_stack aborted: typed confirmation did not match")
            return
    elif "destroy_stack" not in ctx.allow_set:
        resp = await ctx.request_permission("destroy_stack", input_data)
        if _response_kind(resp) == "deny":
            yield AssistantText(delta="destroy_stack aborted: permission denied")
            return
        if _response_kind(resp) == "always_allow_in_session":
            ctx.allow_set.add("destroy_stack")

    async for ev in run_tool(cast(Tool[Any, Any], destroy_stack), input_data, ctx):
        yield ev


async def query(
    *,
    messages: list[Message],
    ctx: LoopContext,
    provider: Provider,
    model: str | None = None,
) -> AsyncIterator[LoopEvent]:
    """CurrentBackend loop: provider-driven tool execution."""
    user_config = load_user_config()
    root_policy_path = Path(ctx.cwd) / "project-policies.yaml"
    legacy_policy_path = Path(ctx.cwd) / ".docker-agent" / "policies.yaml"
    project_policy_path = (
        str(root_policy_path) if root_policy_path.exists() else str(legacy_policy_path)
    )

    if not root_policy_path.exists() and not legacy_policy_path.exists():
        mode = user_config.defaults.missing_project_policy
        if mode == "deny":
            default_content = "project:\n  hardDeny: []\n  require: []\n"
            resp = await ctx.request_permission(
                "initialize_project_policy",
                {
                    "reason": (
                        "Project policy file (project-policies.yaml) is missing "
                        "but required by configuration."
                    ),
                    "path": str(root_policy_path),
                    "content": default_content,
                },
            )
            if _response_kind(resp) in ("approve", "always_allow_in_session"):
                try:
                    root_policy_path.write_text(default_content, encoding="utf-8")
                    project_policy_path = str(root_policy_path)
                    yield AssistantText(
                        delta=(
                            f"[docker-agent] Initialized default project policy at "
                            f"{root_policy_path}\n"
                        )
                    )
                except OSError as err:
                    yield AssistantText(
                        delta=f"[docker-agent] Failed to initialize project policy: {err}\n"
                    )

    policy_engine = PolicyEngine(user_config=user_config, project_policy_path=project_policy_path)
    # Mutate the caller's list in place so appended assistant/tool-result messages
    # propagate back to QueryEngine for persistence and resume.
    working_messages = messages

    last_user = next(
        (m for m in reversed(working_messages) if isinstance(m, UserMessage)),
        None,
    )

    if last_user is not None and is_destroy_all_prompt(last_user.content):
        typed = await ctx.request_typed_confirm(
            "DESTROY ALL",
            f"This will destroy {len(ctx.state_store.list())} stacks.",
        )
        typed_value = typed.get("value") if isinstance(typed, dict) else typed.value
        if _response_kind(typed) != "typed_confirm_value" or typed_value != "DESTROY ALL":
            yield AssistantText(delta="destroy_all aborted: typed confirmation did not match")
            return
        parsed = destroy_all_stacks.input_schema.model_validate({})
        async for ev in run_tool(cast(Tool[Any, Any], destroy_all_stacks), parsed, ctx):
            yield ev
        return

    direct_destroy = (
        parse_direct_destroy_stack(last_user.content) if last_user is not None else None
    )
    if direct_destroy is not None:
        async for ev in run_direct_destroy_stack(
            str(direct_destroy["stack_name"]),
            bool(direct_destroy["remove_volumes"]),
            ctx,
        ):
            yield ev
        return

    iteration = 0
    for iteration in range(MAX_ITERATIONS):
        if ctx.abort_signal.is_set():
            return
        yield IterationStart(n=iteration + 1)

        collected = ProviderTurnResult()
        async for ev in run_provider(provider, working_messages, ctx, model, collected):
            yield ev

        if collected.stop_reason == "max_tokens":
            yield Error(error=RuntimeError("provider response stopped: max tokens reached"))
            return

        # --- ReAct trace: log full Thought for this reasoning step ---
        if ctx.logger is not None and collected.text:
            from docker_agent.state.logger import LogEntry

            ctx.logger.log(
                LogEntry(
                    ts=datetime.now(UTC).isoformat(),
                    level="info",
                    session_id=ctx.session_id or "unknown",
                    iteration=iteration + 1,
                    category="thought",
                    message="full thought",
                    data={"text": collected.text},
                )
            )

        blocks = assistant_blocks_from_collected(collected.text, collected.tool_uses)
        if blocks:
            working_messages.append(AssistantMessage(content=blocks))

        if not collected.tool_uses:
            return

        for tu in collected.tool_uses:
            if ctx.abort_signal.is_set():
                return

            if tu.name == "plan_stack":
                events, result = await handle_plan_stack_tool_use(tu, ctx, policy_engine)
                for ev in events:
                    yield ev
                working_messages.append(
                    ToolResultMessage(
                        toolUseId=tu.id,
                        content=result.get("result_message", ""),
                        isError=result.get("is_error", False),
                    )
                )
                if result.get("user_declined"):
                    return
                continue

            if tu.name == "destroy_all_stacks":
                typed = await ctx.request_typed_confirm(
                    "DESTROY ALL",
                    f"This will destroy {len(ctx.state_store.list())} stacks.",
                )
                typed_value = typed.get("value") if isinstance(typed, dict) else typed.value
                if _response_kind(typed) != "typed_confirm_value" or typed_value != "DESTROY ALL":
                    working_messages.append(
                        ToolResultMessage(
                            toolUseId=tu.id,
                            content="destroy_all aborted: typed confirmation did not match",
                            isError=False,
                        )
                    )
                    continue
                try:
                    parsed = destroy_all_stacks.input_schema.model_validate(
                        json.loads(tu.args_partial or "{}")
                    )
                except Exception as err:
                    working_messages.append(
                        ToolResultMessage(
                            toolUseId=tu.id,
                            content=f"validation failed: {err}",
                            isError=True,
                        )
                    )
                    continue
                tool_events, result = await _drain_tool_stream(
                    run_tool(cast(Tool[Any, Any], destroy_all_stacks), parsed, ctx)
                )
                for ev in tool_events:
                    yield ev
                working_messages.append(
                    ToolResultMessage(
                        toolUseId=tu.id,
                        content=json.dumps(
                            result.model_dump(by_alias=True)
                            if hasattr(result, "model_dump")
                            else result
                        ),
                        isError=False,
                    )
                )
                continue

            if tu.name == "remediate_drift":
                events, result = await handle_remediate_drift_tool_use(tu, ctx, policy_engine)
                for ev in events:
                    yield ev
                working_messages.append(
                    ToolResultMessage(
                        toolUseId=tu.id,
                        content=result.get("result_message", ""),
                        isError=result.get("is_error", False),
                    )
                )
                if result.get("user_declined"):
                    return
                continue

            tool = find_tool_by_name(get_agent_tools(), tu.name)
            if tool is None:
                working_messages.append(
                    ToolResultMessage(
                        toolUseId=tu.id,
                        content=f"unknown tool: {tu.name}",
                        isError=True,
                    )
                )
                continue

            try:
                tool_input: Any = tool.input_schema.model_validate(
                    json.loads(tu.args_partial or "{}")
                )
            except Exception as err:
                working_messages.append(
                    ToolResultMessage(
                        toolUseId=tu.id,
                        content=f"validation failed: {err}",
                        isError=True,
                    )
                )
                continue

            if tool.name == "destroy_stack":
                stack = getattr(tool_input, "stack_name", "")
                remove_volumes = getattr(tool_input, "remove_volumes", None)
                if remove_volumes:
                    phrase = f"DESTROY {stack}"
                    typed = await ctx.request_typed_confirm(
                        phrase,
                        f"This will destroy the stack {stack} and delete all its volumes.",
                    )
                    typed_value = typed.get("value") if isinstance(typed, dict) else typed.value
                    if _response_kind(typed) != "typed_confirm_value" or typed_value != phrase:
                        working_messages.append(
                            ToolResultMessage(
                                toolUseId=tu.id,
                                content="destroy_stack aborted: typed confirmation did not match",
                                isError=False,
                            )
                        )
                        continue
                elif tool.name not in ctx.allow_set:
                    resp = await ctx.request_permission(tool.name, tool_input)
                    if _response_kind(resp) == "deny":
                        working_messages.append(
                            ToolResultMessage(
                                toolUseId=tu.id,
                                content="User denied permission.",
                                isError=False,
                            )
                        )
                        continue
                    if _response_kind(resp) == "always_allow_in_session":
                        ctx.allow_set.add(tool.name)
            elif tool.needs_permission(tool_input):
                if tool.name not in ctx.allow_set:
                    resp = await ctx.request_permission(tool.name, tool_input)
                    if _response_kind(resp) == "deny":
                        working_messages.append(
                            ToolResultMessage(
                                toolUseId=tu.id,
                                content="User denied permission.",
                                isError=False,
                            )
                        )
                        continue
                    if _response_kind(resp) == "always_allow_in_session":
                        ctx.allow_set.add(tool.name)

            tool_events, result = await _drain_tool_stream(run_tool(tool, tool_input, ctx))
            for ev in tool_events:
                yield ev
            working_messages.append(
                ToolResultMessage(
                    toolUseId=tu.id,
                    content=json.dumps(
                        result.model_dump(by_alias=True)
                        if hasattr(result, "model_dump")
                        else result
                    ),
                    isError=False,
                )
            )

        if ctx.logger is not None:
            from docker_agent.state.logger import LogEntry

            actions = [tu.name for tu in collected.tool_uses]
            ctx.logger.log(
                LogEntry(
                    ts=datetime.now(UTC).isoformat(),
                    level="info",
                    session_id=ctx.session_id or "unknown",
                    iteration=iteration + 1,
                    category="iteration_summary",
                    message=f"iteration {iteration + 1}: {len(actions)} action(s)",
                    data={
                        "thoughtLength": len(collected.text),
                        "actions": actions,
                        "stopReason": collected.stop_reason,
                    },
                )
            )

    yield AssistantText(delta=build_graceful_summary(working_messages, MAX_ITERATIONS))


__all__ = ["MAX_ITERATIONS", "format_plan_blocker", "query", "run_provider", "run_tool"]
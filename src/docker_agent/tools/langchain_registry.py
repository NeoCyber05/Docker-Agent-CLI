"""Native LangChain tool registry for the Python agent."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt
from pydantic import BaseModel

from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.query import format_plan_blocker
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.state.state_store import HistoryEvent
from docker_agent.tools import _registry
from docker_agent.tools.base import ToolDone, ToolProgress
from docker_agent.tools.plan_stack import PlanStackResultOk, plan_stack
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.tools.shared.spec_schemas import StackDraft
from docker_agent.types.events import ToolCall, ToolResult
from docker_agent.types.events import ToolProgress as ToolProgressEvent
from docker_agent.types.permissions import permission_kind, permission_value


class _RuntimeStructuredTool(StructuredTool):
    """StructuredTool variant that validates model args before runtime injection."""

    def _to_args_and_kwargs(
        self,
        tool_input: str | dict[str, Any],
        tool_call_id: str | None,
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        schema = self.args_schema
        if (
            isinstance(tool_input, dict)
            and self._injected_args_keys
            and isinstance(schema, type)
            and issubclass(schema, BaseModel)
        ):
            injected = {
                key: tool_input[key]
                for key in self._injected_args_keys
                if key in tool_input
            }
            model_input = {
                key: value
                for key, value in tool_input.items()
                if key not in self._injected_args_keys
            }
            parsed = schema.model_validate(model_input).model_dump()
            return (), {**parsed, **injected}
        return super()._to_args_and_kwargs(tool_input, tool_call_id)

def _runtime_context(runtime: ToolRuntime) -> dict[str, Any]:
    context = runtime.context
    if not isinstance(context, dict):
        raise RuntimeError("docker-agent LangChain tools require dict runtime context")
    return context


def _runtime_value(runtime: ToolRuntime, key: str) -> Any:
    context = _runtime_context(runtime)
    if key not in context:
        raise RuntimeError(f"missing LangChain tool runtime context value: {key}")
    return context[key]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if hasattr(value, "__dict__"):
        return value.__dict__
    return value


async def _destructive_tool_guard(tool: Any, parsed: Any, ctx: Any) -> tuple[bool, str | None]:
    if tool.name == "destroy_all_stacks":
        resp = await ctx.request_typed_confirm(
            "DESTROY ALL",
            f"This will destroy {len(ctx.state_store.list())} stacks.",
        )
        typed_ok = permission_kind(resp) == "typed_confirm_value"
        if not typed_ok or permission_value(resp) != "DESTROY ALL":
            return True, "destroy_all aborted: typed confirmation did not match"
        return True, None

    if tool.name == "destroy_stack" and bool(getattr(parsed, "remove_volumes", False)):
        stack_name = getattr(parsed, "stack_name", "")
        phrase = f"DESTROY {stack_name}"
        resp = await ctx.request_typed_confirm(
            phrase,
            f"This will destroy the stack {stack_name} and delete all its volumes.",
        )
        if permission_kind(resp) != "typed_confirm_value" or permission_value(resp) != phrase:
            return True, "destroy_stack aborted: typed confirmation did not match"
        return True, None

    if tool.name == "remove_container":
        containers = getattr(parsed, "containers", []) or []
        count = len(containers)
        if count >= 3:
            phrase = f"REMOVE {count} CONTAINERS"
            resp = await ctx.request_typed_confirm(
                phrase,
                f"This will force-remove {count} Docker containers.",
            )
            if permission_kind(resp) != "typed_confirm_value" or permission_value(resp) != phrase:
                return False, "remove_container aborted: typed confirmation did not match"

    return False, None


async def _drain_tool(tool: Any, parsed: Any, ctx: Any, emit: Callable[[Any], None]) -> Any:
    emit(ToolCall(name=tool.name, input=parsed))
    result: Any = None
    async for item in tool.call(parsed, ctx):
        if isinstance(item, ToolDone):
            result = item.result
        elif isinstance(item, ToolProgress):
            emit(ToolProgressEvent(msg=item.msg))
    emit(ToolResult(name=tool.name, output=result))
    return result


async def _run_legacy_tool(tool: Any, runtime: ToolRuntime, **kwargs: Any) -> str:
    ctx = _runtime_value(runtime, "ctx")
    emit = _runtime_value(runtime, "emit")
    parsed = tool.input_schema.model_validate(kwargs)
    skip_permission, abort_message = await _destructive_tool_guard(tool, parsed, ctx)
    if abort_message is not None:
        return abort_message

    if not skip_permission and tool.needs_permission(parsed) and tool.name not in ctx.allow_set:
        resp = await ctx.request_permission(tool.name, parsed)
        if permission_kind(resp) == "deny":
            return "User denied permission."
        if permission_kind(resp) == "always_allow_in_session":
            ctx.allow_set.add(tool.name)

    result = await _drain_tool(tool, parsed, ctx, emit)
    if isinstance(result, str):
        return result
    return json.dumps(_jsonable(result), default=str)


def _wrap_legacy_tool(tool: Any) -> BaseTool:
    async def coroutine(runtime: ToolRuntime, **kwargs: Any) -> str:
        return await _run_legacy_tool(tool, runtime, **kwargs)

    risk = (
        "high"
        if tool.needs_permission(tool.input_schema.model_construct())
        else "normal"
    )
    return _RuntimeStructuredTool.from_function(
        coroutine=coroutine,
        name=tool.name,
        description=tool.description,
        args_schema=tool.input_schema,
        metadata={"risk": risk},
    )


async def _run_plan_stack(input_data: StackDraft, ctx: Any, emit: Callable[[Any], None]) -> Any:
    return await _drain_tool(plan_stack, input_data, ctx, emit)


def _plan_confirm_payload(
    plan_result: PlanStackResultOk,
    parsed_input: StackDraft,
    ctx: Any,
) -> dict[str, Any]:
    secret_keys = collect_secret_keys(
        parsed_input.stack_name,
        SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store),
    )
    payload: dict[str, Any] = {
        "compose_yaml": plan_result.compose_yaml,
        "diff": plan_result.diff,
        "hash": plan_result.hash,
    }
    if plan_result.auto_generated_secrets:
        payload["auto_generated_secrets"] = [
            {"service": s.service, "keys": s.keys}
            for s in plan_result.auto_generated_secrets
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


async def _deploy_stack(runtime: ToolRuntime, **kwargs: Any) -> str:
    ctx = _runtime_value(runtime, "ctx")
    emit = _runtime_value(runtime, "emit")
    policy_engine: PolicyEngine = _runtime_value(runtime, "policy_engine")
    parsed_input = StackDraft.model_validate(kwargs)

    result = await _run_plan_stack(parsed_input, ctx, emit)
    if result.blocked:
        return format_plan_blocker(result)

    plan_result: PlanStackResultOk = result
    violations = policy_engine.evaluate(plan_result.compose_yaml)
    if violations:
        msgs = "\n".join(f"[{v.service}] {v.rule}: {v.message}" for v in violations)
        return f"Policy violation(s) detected. Deployment is blocked:\n{msgs}"

    ctx.state_store.append_history(
        HistoryEvent(
            ts=datetime.now(UTC).isoformat(),
            session_id=ctx.session_id or "unknown",
            stack_name=parsed_input.stack_name,
            action="plan",
            details={"hash": plan_result.hash},
        )
    )

    confirm = interrupt(_plan_confirm_payload(plan_result, parsed_input, ctx))
    if permission_kind(confirm) != "approve":
        return "plan denied by user"

    from docker_agent.engine.nodes.apply_with_rollback import (
        ApplyWithRollbackParams,
        run_apply_with_rollback,
    )

    apply_result = await run_apply_with_rollback(
        ApplyWithRollbackParams(
            stack_name=parsed_input.stack_name,
            desired_yaml=plan_result.compose_yaml,
            config_files=plan_result.config_files,
            secret_files=plan_result.staged_secret_files,
            ctx=ctx,
            emit=emit,
            scale_overrides=(
                plan_result.scale_overrides if plan_result.scale_overrides else None
            ),
        )
    )
    return apply_result.result_message


_DEPLOY_STACK_TOOL = _RuntimeStructuredTool.from_function(
    coroutine=_deploy_stack,
    name="deploy_stack",
    description=(
        "Create a reviewed Docker Compose deployment plan, request user approval, "
        "then apply it with rollback protection."
    ),
    args_schema=StackDraft,
    metadata={"risk": "high"},
)


def get_langchain_tools() -> list[BaseTool]:
    """Return the native LangChain tools visible to the model."""
    exposed = []
    for tool in _registry.get_agent_tools():
        if tool.name == "plan_stack":
            continue
        exposed.append(_wrap_legacy_tool(tool))
    return [*exposed, _DEPLOY_STACK_TOOL]


def high_risk_tool_names(tools: Sequence[BaseTool] | None = None) -> set[str]:
    candidates = tools or get_langchain_tools()
    return {tool.name for tool in candidates if (tool.metadata or {}).get("risk") == "high"}


__all__ = ["get_langchain_tools", "high_risk_tool_names"]
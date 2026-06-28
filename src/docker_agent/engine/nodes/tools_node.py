"""Tools node: execute non-special tool uses.

Parity: ``src/backend/langgraph/nodes/toolsNode.ts``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from docker_agent.engine.adapters.tool_adapter import run_tool
from docker_agent.engine.state import AgentState, PendingToolResult
from docker_agent.tool import find_tool_by_name
from docker_agent.tools import get_agent_tools
from docker_agent.tools.destroy_stack import DestroyStackInput
from docker_agent.tools.remove_container import RemoveContainerInput
from docker_agent.tools.shared.spec_schemas import format_validation_error
from docker_agent.types.events import ToolCall, ToolProgress, ToolResult
from docker_agent.types.message import ToolResultMessage
from docker_agent.types.permissions import permission_kind, permission_value

READ_ONLY_ALLOWLIST = {
    "validate_spec",
    "resolve_dependency",
    "check_port_conflict",
    "list_stacks",
    "inspect_drift",
    "get_stack_status",
    "get_health",
    "get_logs",
    "pull_image",
    "exec_docker",
}

EXECUTABLE_TOOLS = READ_ONLY_ALLOWLIST | {
    "destroy_stack",
    "stop_stack",
    "remove_container",
}

REPEAT_TOOL_THRESHOLD = 3


def _block_type(block: Any) -> str | None:
    return getattr(block, "type", None)


def _tool_use_blocks(content: list[Any]) -> list[Any]:
    return [b for b in content if _block_type(b) == "tool_use"]


def _normalize_tool_input(tool_input: Any) -> str:
    if hasattr(tool_input, "model_dump"):
        data = tool_input.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(tool_input, dict):
        data = tool_input
    else:
        return json.dumps(tool_input, default=str, sort_keys=True)
    return json.dumps(data, sort_keys=True, default=str)


def _count_matching_tool_uses(
    messages: list[Any], tool_name: str, normalized_input: str
) -> int:
    count = 0
    for msg in messages:
        if msg.role != "assistant":
            continue
        for block in msg.content or []:
            if _block_type(block) != "tool_use":
                continue
            if getattr(block, "name", None) != tool_name:
                continue
            block_input = getattr(block, "input", {})
            if _normalize_tool_input(block_input) == normalized_input:
                count += 1
    return count


def _loop_guard_message(tool_name: str, repeat_count: int) -> str:
    return (
        f"Loop guard: tool {tool_name} was already invoked {repeat_count} times with the "
        "same parameters. Stop retrying silently — explain the situation to the user or "
        "ask for guidance."
    )


@dataclass
class ToolsNodeDeps:
    ctx: Any
    emit: Callable[[Any], None]


async def _execute_tool_use(
    tool: Any,
    parsed: Any,
    tu: Any,
    deps: ToolsNodeDeps,
) -> PendingToolResult:
    deps.emit(ToolCall(name=tool.name, input=parsed))
    run = await run_tool(tool, parsed, deps.ctx)
    for p in run.progress:
        deps.emit(ToolProgress(msg=p.msg))
    deps.emit(ToolResult(name=tool.name, output=run.output))
    return PendingToolResult(
        tool_use_id=tu.id,
        name=tool.name,
        input=parsed,
        output=run.output,
        is_error=run.is_error,
    )


async def tools_node(deps: ToolsNodeDeps, state: AgentState) -> dict[str, Any]:
    last = state.messages[-1] if state.messages else None
    if not last or last.role != "assistant":
        return {}

    tool_uses = [
        b
        for b in _tool_use_blocks(last.content)
        if getattr(b, "name", None) not in ("plan_stack", "remediate_drift")
    ]

    results: list[PendingToolResult] = []
    for tu in tool_uses:
        if deps.ctx.abort_signal.is_set():
            break

        tool = find_tool_by_name(get_agent_tools(), tu.name)
        if not tool:
            results.append(
                PendingToolResult(
                    tool_use_id=tu.id,
                    name=tu.name,
                    input=tu.input,
                    output=f"unknown tool: {tu.name}",
                    is_error=True,
                )
            )
            continue

        try:
            parsed = tool.input_schema.model_validate(tu.input)
        except ValidationError as err:
            results.append(
                PendingToolResult(
                    tool_use_id=tu.id,
                    name=tool.name,
                    input=tu.input,
                    output=f"validation failed: {format_validation_error(err)}",
                    is_error=True,
                )
            )
            continue
        except Exception as err:
            results.append(
                PendingToolResult(
                    tool_use_id=tu.id,
                    name=tool.name,
                    input=tu.input,
                    output=f"validation failed: {err}",
                    is_error=True,
                )
            )
            continue

        normalized_input = _normalize_tool_input(parsed)
        repeat_count = _count_matching_tool_uses(state.messages, tool.name, normalized_input)
        if repeat_count >= REPEAT_TOOL_THRESHOLD:
            results.append(
                PendingToolResult(
                    tool_use_id=tu.id,
                    name=tool.name,
                    input=parsed,
                    output=_loop_guard_message(tool.name, repeat_count),
                    is_error=False,
                )
            )
            continue

        if tool.name == "destroy_all_stacks":
            resp = await deps.ctx.request_typed_confirm(
                "DESTROY ALL",
                f"This will destroy {len(deps.ctx.state_store.list())} stacks.",
            )
            if (
                permission_kind(resp) != "typed_confirm_value"
                or permission_value(resp) != "DESTROY ALL"
            ):
                results.append(
                    PendingToolResult(
                        tool_use_id=tu.id,
                        name=tool.name,
                        input=parsed,
                        output="destroy_all aborted: typed confirmation did not match",
                        is_error=False,
                    )
                )
                continue
            results.append(await _execute_tool_use(tool, parsed, tu, deps))
            continue

        if tool.name == "destroy_stack":
            destroy_input = DestroyStackInput.model_validate(parsed.model_dump())
            remove_volumes = destroy_input.remove_volumes or False
            if remove_volumes:
                stack_name = destroy_input.stack_name
                phrase = f"DESTROY {stack_name}"
                resp = await deps.ctx.request_typed_confirm(
                    phrase,
                    f"This will destroy the stack {stack_name} and delete all its volumes.",
                )
                if (
                    permission_kind(resp) != "typed_confirm_value"
                    or permission_value(resp) != phrase
                ):
                    results.append(
                        PendingToolResult(
                            tool_use_id=tu.id,
                            name=tool.name,
                            input=parsed,
                            output="destroy_stack aborted: typed confirmation did not match",
                            is_error=False,
                        )
                    )
                    continue
                results.append(await _execute_tool_use(tool, parsed, tu, deps))
                continue

        if tool.name == "remove_container":
            remove_input = RemoveContainerInput.model_validate(parsed.model_dump())
            count = len(remove_input.containers)
            if count >= 3:
                phrase = f"REMOVE {count} CONTAINERS"
                resp = await deps.ctx.request_typed_confirm(
                    phrase,
                    f"This will force-remove {count} Docker containers.",
                )
                if (
                    permission_kind(resp) != "typed_confirm_value"
                    or permission_value(resp) != phrase
                ):
                    results.append(
                        PendingToolResult(
                            tool_use_id=tu.id,
                            name=tool.name,
                            input=parsed,
                            output="remove_container aborted: typed confirmation did not match",
                            is_error=False,
                        )
                    )
                    continue

        if tool.name not in EXECUTABLE_TOOLS:
            results.append(
                PendingToolResult(
                    tool_use_id=tu.id,
                    name=tool.name,
                    input=parsed,
                    output="tool not supported in langgraph backend (phase 3)",
                    is_error=True,
                )
            )
            continue

        if tool.needs_permission(parsed) and tool.name not in deps.ctx.allow_set:
            resp = await deps.ctx.request_permission(tool.name, parsed)
            if permission_kind(resp) == "deny":
                results.append(
                    PendingToolResult(
                        tool_use_id=tu.id,
                        name=tool.name,
                        input=parsed,
                        output="User denied permission.",
                        is_error=False,
                    )
                )
                continue
            if permission_kind(resp) == "always_allow_in_session":
                deps.ctx.allow_set.add(tool.name)

        results.append(await _execute_tool_use(tool, parsed, tu, deps))

    tool_messages = [
        ToolResultMessage(
            role="tool",
            toolUseId=r.tool_use_id,
            content=r.output if isinstance(r.output, str) else json.dumps(r.output, default=str),
            isError=r.is_error,
        )
        for r in results
    ]
    return {"messages": tool_messages, "pending_tool_results": results}
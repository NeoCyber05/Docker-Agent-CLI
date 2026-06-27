"""Tools node: execute non-special tool uses.

Parity: ``src/backend/langgraph/nodes/toolsNode.ts``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docker_agent.backend.langgraph.adapters.tool_adapter import run_tool
from docker_agent.backend.langgraph.state import AgentState, PendingToolResult
from docker_agent.tool import find_tool_by_name
from docker_agent.tools import get_agent_tools
from docker_agent.tools.destroy_stack import DestroyStackInput
from docker_agent.types.events import ToolCall, ToolProgress, ToolResult
from docker_agent.types.message import ToolResultMessage

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


def _block_type(block: Any) -> str | None:
    return getattr(block, "type", None)


def _tool_use_blocks(content: list[Any]) -> list[Any]:
    return [b for b in content if _block_type(b) == "tool_use"]


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

        if tool.name == "destroy_all_stacks":
            resp = await deps.ctx.request_typed_confirm(
                "DESTROY ALL",
                f"This will destroy {len(deps.ctx.state_store.list())} stacks.",
            )
            if resp.get("kind") != "typed_confirm_value" or resp.get("value") != "DESTROY ALL":
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
                if resp.get("kind") != "typed_confirm_value" or resp.get("value") != phrase:
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

        if tool.name not in READ_ONLY_ALLOWLIST and tool.name != "destroy_stack":
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
            if resp.get("kind") == "deny":
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
            if resp.get("kind") == "always_allow_in_session":
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
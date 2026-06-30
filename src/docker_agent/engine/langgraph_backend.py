"""LangGraphBackend orchestrator.

Parity: ``src/backend/langgraph/LangGraphBackend.ts``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langgraph.types import Command

from docker_agent.agent import AgentBackend, BackendQueryParams
from docker_agent.config import load_user_config
from docker_agent.core.iteration_limits import derive_recursion_limit
from docker_agent.engine.adapters.tool_adapter import run_tool
from docker_agent.engine.graph import GraphDeps, build_graph
from docker_agent.engine.state import AgentState
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.tools.destroy_all_stacks import destroy_all_stacks
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.types.events import (
    AssistantText,
    Error,
    LoopEvent,
    ToolCall,
    ToolProgress,
    ToolResult,
)
from docker_agent.types.permissions import permission_kind, permission_value


def _is_destroy_all_prompt(content: str) -> bool:
    return content.strip().lower() == "destroy all stacks"


def _parse_direct_destroy_stack(content: str) -> dict[str, Any] | None:
    trimmed = content.strip()
    patterns = [
        re.compile(r"^Destroy stack (\S+)(?:\s+with volumes)?$", re.IGNORECASE),
        re.compile(r"^destroy (\S+)(?:\s+with volumes)?$", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.match(trimmed)
        if not match or not match.group(1) or match.group(1).lower() == "all":
            continue
        return {
            "stack_name": match.group(1),
            "remove_volumes": bool(re.search(r"\swith volumes$", trimmed, re.IGNORECASE)),
        }
    return None


async def _run_tool_events(
    tool: Any,
    input_data: Any,
    ctx: Any,
    emit: Any,
) -> Any:
    emit(ToolCall(name=tool.name, input=input_data))
    run = await run_tool(tool, input_data, ctx)
    for p in run.progress:
        emit(ToolProgress(msg=p.msg))
    emit(ToolResult(name=tool.name, output=run.output))
    return run.output


class LangGraphBackend(AgentBackend):
    name = "langgraph"

    async def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]:
        queue: asyncio.Queue[LoopEvent | None] = asyncio.Queue()

        def emit(ev: Any) -> None:
            queue.put_nowait(ev)

        async def runner() -> None:
            try:
                user_config = load_user_config()
                cwd = Path(params.ctx.cwd)
                root_policy = cwd / "project-policies.yaml"
                legacy_policy = cwd / ".docker-agent" / "policies.yaml"
                project_policy_path = str(
                    root_policy if root_policy.exists() else legacy_policy
                )

                if not root_policy.exists() and not legacy_policy.exists():
                    mode = user_config.defaults.missing_project_policy
                    if mode == "deny":
                        default_content = "project:\n  hardDeny: []\n  require: []\n"
                        resp = await params.ctx.request_permission(
                            "initialize_project_policy",
                            {
                                "reason": (
                                    "Project policy file (project-policies.yaml) is missing "
                                    "but required by configuration."
                                ),
                                "path": str(root_policy),
                                "content": default_content,
                            },
                        )
                        if permission_kind(resp) in ("approve", "always_allow_in_session"):
                            try:
                                root_policy.write_text(default_content, encoding="utf-8")
                                project_policy_path = str(root_policy)
                                emit(
                                    AssistantText(
                                        delta=(
                                            f"[docker-agent] Initialized default project "
                                            f"policy at {root_policy}\n"
                                        )
                                    )
                                )
                            except Exception as err:
                                emit(
                                    AssistantText(
                                        delta=(
                                            f"[docker-agent] Failed to initialize project "
                                            f"policy: {err}\n"
                                        )
                                    )
                                )

                policy_engine = PolicyEngine(
                    user_config=user_config,
                    project_policy_path=project_policy_path,
                )

                messages = list(params.messages)
                last_user = next(
                    (m for m in reversed(messages) if m.role == "user"),
                    None,
                )

                if last_user is not None and _is_destroy_all_prompt(last_user.content):
                    typed = await params.ctx.request_typed_confirm(
                        "DESTROY ALL",
                        f"This will destroy {len(params.ctx.state_store.list())} stacks.",
                    )
                    if (
                        permission_kind(typed) != "typed_confirm_value"
                        or permission_value(typed) != "DESTROY ALL"
                    ):
                        emit(
                            AssistantText(
                                delta="destroy_all aborted: typed confirmation did not match"
                            )
                        )
                        return
                    parsed = destroy_all_stacks.input_schema.model_validate({})
                    await _run_tool_events(destroy_all_stacks, parsed, params.ctx, emit)
                    return

                direct_destroy = (
                    _parse_direct_destroy_stack(last_user.content)
                    if last_user is not None
                    else None
                )
                if direct_destroy is not None:
                    input_data = destroy_stack.input_schema.model_validate(
                        {
                            "stack_name": direct_destroy["stack_name"],
                            **(
                                {"remove_volumes": True}
                                if direct_destroy["remove_volumes"]
                                else {}
                            ),
                        }
                    )
                    if direct_destroy["remove_volumes"]:
                        phrase = f"DESTROY {direct_destroy['stack_name']}"
                        typed = await params.ctx.request_typed_confirm(
                            phrase,
                            (
                                f"This will destroy the stack {direct_destroy['stack_name']} "
                                "and delete all its volumes."
                            ),
                        )
                        typed_ok = permission_kind(typed) == "typed_confirm_value"
                        if not typed_ok or permission_value(typed) != phrase:
                            emit(
                                AssistantText(
                                    delta="destroy_stack aborted: typed confirmation did not match"
                                )
                            )
                            return
                    elif "destroy_stack" not in params.ctx.allow_set:
                        resp = await params.ctx.request_permission(
                            "destroy_stack", input_data
                        )
                        if permission_kind(resp) == "deny":
                            emit(
                                AssistantText(
                                    delta="destroy_stack aborted: permission denied"
                                )
                            )
                            return
                        if permission_kind(resp) == "always_allow_in_session":
                            params.ctx.allow_set.add("destroy_stack")
                    await _run_tool_events(destroy_stack, input_data, params.ctx, emit)
                    return

                graph = build_graph(
                    GraphDeps(
                        provider=params.provider,
                        ctx=params.ctx,
                        model=params.model,
                        emit=emit,
                        policy_engine=policy_engine,
                    )
                )

                initial_state = AgentState(
                    messages=messages,
                    iter=0,
                    allow_set=params.ctx.allow_set,
                    pending_tool_results=[],
                    aborted=False,
                )

                thread_id = params.ctx.session_id or "default"
                config: dict[str, Any] = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": derive_recursion_limit(),
                }

                stream_input: AgentState | Command[Any] = initial_state
                while True:
                    interrupted = False
                    async for event in graph.astream(stream_input, config):
                        if params.ctx.abort_signal.is_set():
                            return
                        if isinstance(event, dict) and "__interrupt__" in event:
                            interrupted = True
                            interrupt_payload = event["__interrupt__"][0].value
                            confirm = await params.ctx.request_confirm(interrupt_payload)
                            stream_input = Command[Any](resume=confirm)
                            break
                    if not interrupted:
                        break

                final_state = await graph.aget_state(config)
                final_values = getattr(final_state, "values", None)
                final_messages = None
                if isinstance(final_values, dict):
                    final_messages = final_values.get("messages")
                elif final_values is not None:
                    final_messages = getattr(final_values, "messages", None)
                if final_messages is not None:
                    params.messages[:] = final_messages
            except Exception as err:
                if not params.ctx.abort_signal.is_set():
                    emit(Error(error=err))
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(runner())
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
        await task
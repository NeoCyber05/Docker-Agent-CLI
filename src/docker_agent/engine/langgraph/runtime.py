"""LangGraphBackend orchestrator using an explicit runtime graph."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from docker_agent.agent import AgentBackend, BackendQueryParams
from docker_agent.config import load_user_config
from docker_agent.core.iteration_limits import derive_recursion_limit
from docker_agent.core.prompt_builder import build_system_prompt
from docker_agent.engine.adapters.tool_adapter import run_tool
from docker_agent.engine.langgraph.graph import build_langgraph_runtime_graph
from docker_agent.engine.langgraph.model_factory import create_chat_model
from docker_agent.mcp.capabilities import (
    _coerce_payload as _coerce_mcp_payload,
)
from docker_agent.mcp.capabilities import (
    load_mcp_capabilities,
    mcp_command_specs,
    mcp_commit_tool_name,
    mcp_context_summary,
    mcp_high_risk_tool_names,
    mcp_rollback_tool_name,
    model_visible_mcp_tools,
)
from docker_agent.mcp.client import load_mcp_langchain_tools
from docker_agent.mcp.commands import CommandMatch, match_command
from docker_agent.mcp.config import is_mcp_enabled
from docker_agent.policy.defaults import ensure_global_policy
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.tools.destroy_all_stacks import destroy_all_stacks
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.tools.langchain_registry import get_langchain_tools, high_risk_tool_names
from docker_agent.tools.stop_stack import stop_stack
from docker_agent.types.events import (
    AssistantText,
    Error,
    IterationStart,
    LoopEvent,
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
from docker_agent.types.permissions import permission_kind, permission_value
from docker_agent.vault.api_key_store import resolve_stored_api_key

_MULTI_HIGH_RISK_MSG = "Only one high-risk tool may be called per turn. Call them one at a time."


class HighRiskToolCallMiddleware(AgentMiddleware):
    """Reject model responses that request multiple high-impact tools."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    async def awrap_model_call(self, request: Any, handler: Any) -> ModelResponse:
        response = await handler(request)
        messages = list(response.result)
        high_risk_calls = []
        for message in messages:
            if isinstance(message, AIMessage):
                high_risk_calls.extend(
                    call for call in message.tool_calls if call.get("name") in self._names
                )
        if len(high_risk_calls) <= 1:
            return response
        return ModelResponse(result=[AIMessage(content=_MULTI_HIGH_RISK_MSG)])


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


def _parse_direct_stop_stack(content: str) -> dict[str, Any] | None:
    trimmed = content.strip()
    patterns = [
        re.compile(r"^Stop stack (\S+)(?:\s+services?\s+(.+))?$", re.IGNORECASE),
        re.compile(r"^stop (\S+)(?:\s+services?\s+(.+))?$", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.match(trimmed)
        if not match or not match.group(1):
            continue
        stack_name = match.group(1)
        services_raw = match.group(2)
        if services_raw is None:
            return {"stack_name": stack_name}
        services = [part.strip() for part in re.split(r"[,\s]+", services_raw) if part.strip()]
        if not services:
            return {"stack_name": stack_name}
        return {"stack_name": stack_name, "services": services}
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


def _to_langchain_message(message: Message) -> BaseMessage:
    if isinstance(message, UserMessage):
        return HumanMessage(content=message.content)
    if isinstance(message, ToolResultMessage):
        return ToolMessage(
            content=message.content,
            tool_call_id=message.tool_use_id,
            status="error" if message.is_error else "success",
        )
    if isinstance(message, AssistantMessage):
        text = "".join(
            getattr(block, "text", "")
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        tool_calls = [
            {
                "name": block.name,
                "args": block.input,
                "id": block.id,
            }
            for block in message.content
            if getattr(block, "type", None) == "tool_use"
        ]
        return AIMessage(content=text, tool_calls=tool_calls)
    raise TypeError(f"unsupported message type: {type(message)!r}")


def _from_langchain_message(message: BaseMessage) -> Message | None:
    if isinstance(message, HumanMessage):
        content = message.content if isinstance(message.content, str) else str(message.content)
        return UserMessage(content=content)
    if isinstance(message, ToolMessage):
        return ToolResultMessage(
            role="tool",
            toolUseId=message.tool_call_id,
            content=message.content if isinstance(message.content, str) else str(message.content),
            isError=message.status == "error",
        )
    if isinstance(message, AIMessage):
        blocks: list[Any] = []
        if message.content:
            content = message.content if isinstance(message.content, str) else str(message.content)
            blocks.append(AssistantBlock.model_validate({"type": "text", "text": content}))
        for call in message.tool_calls:
            blocks.append(
                AssistantBlock.model_validate(
                    {
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": call.get("name", ""),
                        "input": call.get("args", {}),
                    }
                )
            )
        return AssistantMessage(content=blocks)
    return None


def _emit_model_messages(messages: list[BaseMessage], emit: Any) -> None:
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        if message.content:
            content = message.content if isinstance(message.content, str) else str(message.content)
            emit(AssistantText(delta=content))
        if message.usage_metadata:
            emit(
                Usage(
                    inputTokens=message.usage_metadata.get("input_tokens", 0),
                    outputTokens=message.usage_metadata.get("output_tokens", 0),
                )
            )


async def _api_env_for_provider(provider: Any, provider_name: str) -> dict[str, str]:
    env = dict(os.environ)
    store = getattr(provider, "_api_key_store", None)
    if provider_name in {"openai", "gemini", "openrouter"}:
        key = await resolve_stored_api_key(provider_name, env, store)  # type: ignore[arg-type]
        if key:
            env_var = {
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }[provider_name]
            env[env_var] = key
    return env


async def _run_legacy_command(
    *,
    last_user: UserMessage | None,
    params: BackendQueryParams,
    emit: Any,
) -> bool:
    if last_user is None:
        return False
    if _is_destroy_all_prompt(last_user.content):
        typed = await params.ctx.request_typed_confirm(
            "DESTROY ALL",
            f"This will destroy {len(params.ctx.state_store.list())} stacks.",
        )
        typed_ok = permission_kind(typed) == "typed_confirm_value"
        if not typed_ok or permission_value(typed) != "DESTROY ALL":
            emit(AssistantText(delta="destroy_all aborted: typed confirmation did not match"))
            return True
        parsed = destroy_all_stacks.input_schema.model_validate({})
        await _run_tool_events(destroy_all_stacks, parsed, params.ctx, emit)
        return True

    direct_destroy = _parse_direct_destroy_stack(last_user.content)
    if direct_destroy is not None:
        input_data = destroy_stack.input_schema.model_validate(
            {
                "stack_name": direct_destroy["stack_name"],
                **({"remove_volumes": True} if direct_destroy["remove_volumes"] else {}),
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
                emit(AssistantText(delta="destroy_stack aborted: typed confirmation did not match"))
                return True
        elif "destroy_stack" not in params.ctx.allow_set:
            resp = await params.ctx.request_permission("destroy_stack", input_data)
            if permission_kind(resp) == "deny":
                emit(AssistantText(delta="destroy_stack aborted: permission denied"))
                return True
            if permission_kind(resp) == "always_allow_in_session":
                params.ctx.allow_set.add("destroy_stack")
        await _run_tool_events(destroy_stack, input_data, params.ctx, emit)
        return True

    direct_stop = _parse_direct_stop_stack(last_user.content)
    if direct_stop is not None:
        input_data = stop_stack.input_schema.model_validate(
            {
                "stack_name": direct_stop["stack_name"],
                **({"services": direct_stop["services"]} if direct_stop.get("services") else {}),
            }
        )
        if "stop_stack" not in params.ctx.allow_set:
            resp = await params.ctx.request_permission("stop_stack", input_data)
            if permission_kind(resp) == "deny":
                emit(AssistantText(delta="stop_stack aborted: permission denied"))
                return True
            if permission_kind(resp) == "always_allow_in_session":
                params.ctx.allow_set.add("stop_stack")
        await _run_tool_events(stop_stack, input_data, params.ctx, emit)
        return True
    return False


async def _execute_mcp_command_match(
    match: CommandMatch,
    *,
    tools_by_name: dict[str, Any],
    ctx: Any,
    emit: Any,
) -> None:
    tool = tools_by_name.get(match.tool)
    if tool is None:
        emit(AssistantText(delta=f"{match.tool} is not available from MCP tools"))
        return
    if match.confirmation == "typed":
        phrase = match.phrase or ""
        reason = match.reason or f"Confirm {match.tool}."
        typed = await ctx.request_typed_confirm(phrase, reason)
        if permission_kind(typed) != "typed_confirm_value" or permission_value(typed) != phrase:
            emit(AssistantText(delta=f"{match.tool} aborted: typed confirmation did not match"))
            return
    elif match.confirmation == "permission" and match.tool not in ctx.allow_set:
        resp = await ctx.request_permission(match.tool, match.input)
        if permission_kind(resp) == "deny":
            emit(AssistantText(delta=f"{match.tool} aborted: permission denied"))
            return
        if permission_kind(resp) == "always_allow_in_session":
            ctx.allow_set.add(match.tool)
    await tool.ainvoke(match.input)


def _high_risk_from_capabilities(capabilities: dict[str, Any]) -> set[str]:
    tools = capabilities.get("tools")
    if not isinstance(tools, list):
        return set()
    return {
        str(item.get("name"))
        for item in tools
        if isinstance(item, dict)
        and (item.get("risk") == "high" or item.get("mutating") is True)
        and item.get("name")
    }


async def _run_agent_loop(
    *,
    params: BackendQueryParams,
    emit: Any,
    policy_engine: PolicyEngine,
    tools: list[Any],
    high_risk_tools: set[str],
    context_summary: str,
) -> None:
    provider_name = getattr(params.provider, "name", "unknown")
    params.ctx.provider_name = provider_name
    params.ctx.model = params.model
    env = await _api_env_for_provider(params.provider, provider_name)
    chat_model = create_chat_model(
        provider_name=provider_name,
        model=params.model,
        env=env,
    )
    if not isinstance(chat_model, BaseChatModel):
        raise TypeError("create_chat_model must return a BaseChatModel")

    agent = create_agent(
        model=chat_model,
        tools=tools,
        system_prompt=build_system_prompt(context_summary),
        context_schema=dict,
        checkpointer=MemorySaver(),
        middleware=[HighRiskToolCallMiddleware(high_risk_tools)],
    )

    thread_id = params.ctx.session_id or "default"
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": derive_recursion_limit(),
    }
    context = {
        "ctx": params.ctx,
        "emit": emit,
        "policy_engine": policy_engine,
        "provider_name": provider_name,
        "model": params.model,
    }
    stream_input: dict[str, Any] | Command[Any] = {
        "messages": [_to_langchain_message(m) for m in params.messages]
    }
    emit(IterationStart(n=1))

    while True:
        interrupted = False
        async for event in agent.astream(
            stream_input,
            config=config,
            context=context,
            stream_mode="updates",
        ):
            if params.ctx.abort_signal.is_set():
                return
            if isinstance(event, dict) and "__interrupt__" in event:
                interrupted = True
                interrupt_payload = event["__interrupt__"][0].value
                confirm = await params.ctx.request_confirm(interrupt_payload)
                stream_input = Command[Any](resume=confirm)
                break
            if not isinstance(event, dict):
                continue
            model_update = event.get("model")
            if isinstance(model_update, dict):
                _emit_model_messages(model_update.get("messages", []), emit)

        if not interrupted:
            break

    final_state = await agent.aget_state(config)
    final_values = getattr(final_state, "values", None)
    final_messages = final_values.get("messages") if isinstance(final_values, dict) else None
    if final_messages is not None:
        converted = [
            converted
            for msg in final_messages
            if (converted := _from_langchain_message(msg)) is not None
        ]
        params.messages[:] = converted


class RuntimeLangGraphBackend(AgentBackend):
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
                project_policy_path = str(root_policy)

                if not root_policy.exists():
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

                ensure_global_policy()
                policy_engine = PolicyEngine(
                    user_config=user_config,
                    project_policy_path=project_policy_path,
                )

                last_user = next(
                    (m for m in reversed(params.messages) if m.role == "user"),
                    None,
                )
                mcp_enabled = is_mcp_enabled()
                raw_mcp_tools: list[Any] | None = None
                capabilities: dict[str, Any] = {}

                async def ensure_mcp_tools() -> tuple[list[Any], dict[str, Any]]:
                    nonlocal raw_mcp_tools, capabilities
                    if raw_mcp_tools is None:
                        raw_mcp_tools = await load_mcp_langchain_tools()
                        capabilities = await load_mcp_capabilities(raw_mcp_tools)
                    return raw_mcp_tools, capabilities

                def runtime_args_for_state(state: dict[str, Any]) -> dict[str, Any]:
                    return {
                        "cwd": params.ctx.cwd,
                        "session_id": params.ctx.session_id or "default",
                        "provider_name": str(state.get("provider_name") or "mcp"),
                        "model": state.get("model"),
                    }

                def runtime_args_for_command() -> dict[str, Any]:
                    return {
                        "cwd": params.ctx.cwd,
                        "session_id": params.ctx.session_id or "default",
                        "provider_name": getattr(params.ctx, "provider_name", "mcp"),
                        "model": getattr(params.ctx, "model", None),
                    }

                def stringify_tool_output(value: Any) -> str:
                    try:
                        return json.dumps(value, default=str, ensure_ascii=False)
                    except TypeError:
                        return str(value)

                def append_tool_message(
                    state: dict[str, Any],
                    call: dict[str, Any] | None,
                    output: Any,
                    *,
                    is_error: bool = False,
                ) -> list[BaseMessage]:
                    messages = list(state.get("messages") or [])
                    if call and call.get("id"):
                        messages.append(
                            ToolMessage(
                                content=stringify_tool_output(output),
                                tool_call_id=str(call["id"]),
                                status="error" if is_error else "success",
                            )
                        )
                    return messages

                async def decision_for_pending(action: dict[str, Any]) -> dict[str, Any]:
                    kind = action.get("kind")
                    display = (
                        action.get("display") if isinstance(action.get("display"), dict) else {}
                    )
                    if kind == "plan_review":
                        response = await params.ctx.request_confirm(display)
                        return {
                            "decision": "approve"
                            if permission_kind(response) == "approve"
                            else "deny"
                        }
                    if kind == "typed":
                        phrase = str(display.get("phrase") or action.get("phrase") or "")
                        reason = str(display.get("reason") or action.get("reason") or "")
                        response = await params.ctx.request_typed_confirm(phrase, reason)
                        approved = (
                            permission_kind(response) == "typed_confirm_value"
                            and permission_value(response) == phrase
                        )
                        return {
                            "decision": "approve" if approved else "deny",
                            "typed_phrase": permission_value(response) if approved else None,
                        }
                    if kind == "secrets_input":
                        service = str(display.get("service") or "")
                        keys = list(display.get("keys") or [])
                        reason = str(display.get("reason") or "")
                        response = await params.ctx.request_secrets_input(service, keys, reason)
                        if permission_kind(response) != "secrets_input_values":
                            return {"decision": "deny"}
                        values = (
                            response.get("values", {})
                            if isinstance(response, dict)
                            else response.values
                        )
                        return {"decision": "approve", "secrets": values}
                    if kind == "permission":
                        tool = str(action.get("tool") or "")
                        response = await params.ctx.request_permission(tool, display)
                        return {
                            "decision": "deny" if permission_kind(response) == "deny" else "approve"
                        }
                    return {"decision": "deny"}

                async def invoke_mcp_tool(
                    tool: Any,
                    args: dict[str, Any],
                    runtime_args: dict[str, Any],
                ) -> Any:
                    call_input = {**args, **runtime_args}
                    result = await tool.ainvoke(call_input)
                    return _coerce_mcp_payload(result) or result

                async def context_loader_node(_state: dict[str, Any]) -> dict[str, Any]:
                    if not mcp_enabled:
                        return {"route": "command_router"}
                    raw, caps = await ensure_mcp_tools()
                    visible = model_visible_mcp_tools(raw, capabilities=caps)
                    summary = await mcp_context_summary(
                        raw,
                        capabilities=caps,
                        cwd=params.ctx.cwd,
                        fallback=params.ctx.state_store.summary(),
                    )
                    provider_name = getattr(params.provider, "name", "unknown")
                    langchain_messages: list[BaseMessage] = [
                        SystemMessage(content=build_system_prompt(summary)),
                        *[_to_langchain_message(message) for message in params.messages],
                    ]
                    return {
                        "route": "command_router",
                        "messages": langchain_messages,
                        "mcp_tools": raw,
                        "mcp_tools_by_name": {tool.name: tool for tool in raw},
                        "model_visible_tools": visible,
                        "capabilities": caps,
                        "context_summary": summary,
                        "provider_name": provider_name,
                        "model": params.model,
                        "high_risk_tools": (
                            mcp_high_risk_tool_names(raw, caps) | _high_risk_from_capabilities(caps)
                        ),
                    }

                async def command_router_node(state: dict[str, Any]) -> dict[str, Any]:
                    if not mcp_enabled:
                        handled = await _run_legacy_command(
                            last_user=last_user,
                            params=params,
                            emit=emit,
                        )
                        return {"handled": handled, "route": "finalize" if handled else "reasoning"}
                    if last_user is None:
                        return {"handled": False, "route": "reasoning"}
                    caps = dict(state.get("capabilities") or {})
                    match = match_command(last_user.content, mcp_command_specs(caps))
                    if match is None:
                        return {"handled": False, "route": "reasoning"}
                    tools_by_name = dict(state.get("mcp_tools_by_name") or {})
                    tool = tools_by_name.get(match.tool)
                    if tool is None:
                        emit(AssistantText(delta=f"{match.tool} is not available from MCP tools"))
                        return {"handled": True, "route": "finalize"}
                    if match.confirmation == "typed":
                        phrase = match.phrase or ""
                        reason = match.reason or f"Confirm {match.tool}."
                        typed = await params.ctx.request_typed_confirm(phrase, reason)
                        if (
                            permission_kind(typed) != "typed_confirm_value"
                            or permission_value(typed) != phrase
                        ):
                            emit(
                                AssistantText(
                                    delta=f"{match.tool} aborted: typed confirmation did not match"
                                )
                            )
                            return {"handled": True, "route": "finalize"}
                    elif (
                        match.confirmation == "permission"
                        and match.tool not in params.ctx.allow_set
                    ):
                        resp = await params.ctx.request_permission(match.tool, match.input)
                        if permission_kind(resp) == "deny":
                            emit(AssistantText(delta=f"{match.tool} aborted: permission denied"))
                            return {"handled": True, "route": "finalize"}
                        if permission_kind(resp) == "always_allow_in_session":
                            params.ctx.allow_set.add(match.tool)
                    emit(ToolCall(name=match.tool, input=match.input))
                    result = await invoke_mcp_tool(tool, match.input, runtime_args_for_command())
                    emit(ToolResult(name=match.tool, output=result))
                    if isinstance(result, dict) and result.get("status") == "pending_confirmation":
                        return {
                            "handled": True,
                            "pending_action": result["pending_action"],
                            "route": "human_approval",
                        }
                    return {"handled": True, "route": "finalize"}

                async def reasoning_node(state: dict[str, Any]) -> dict[str, Any]:
                    if not mcp_enabled:
                        provider_name = getattr(params.provider, "name", "unknown")
                        params.ctx.provider_name = provider_name
                        params.ctx.model = params.model
                        tools = get_langchain_tools()
                        await _run_agent_loop(
                            params=params,
                            emit=emit,
                            policy_engine=policy_engine,
                            tools=tools,
                            high_risk_tools=high_risk_tool_names(tools),
                            context_summary=params.ctx.state_store.summary(),
                        )
                        return {"handled": True, "route": "finalize"}

                    loop_count = int(state.get("loop_count") or 0) + 1
                    if loop_count == 1:
                        emit(IterationStart(n=1))
                    if loop_count > derive_recursion_limit():
                        msg = "Reached LangGraph MCP recursion limit."
                        emit(AssistantText(delta=msg))
                        return {"loop_count": loop_count, "route": "finalize"}

                    provider_name = str(state.get("provider_name") or "unknown")
                    env = await _api_env_for_provider(params.provider, provider_name)
                    chat_model = create_chat_model(
                        provider_name=provider_name,
                        model=params.model,
                        env=env,
                    )
                    if not isinstance(chat_model, BaseChatModel):
                        raise TypeError("create_chat_model must return a BaseChatModel")
                    bound_model = chat_model.bind_tools(
                        list(state.get("model_visible_tools") or [])
                    )
                    response = await bound_model.ainvoke(list(state.get("messages") or []))
                    if not isinstance(response, AIMessage):
                        response = AIMessage(content=str(response))

                    tool_calls = [
                        {
                            "name": str(call.get("name") or ""),
                            "args": call.get("args") or {},
                            "id": str(call.get("id") or ""),
                        }
                        for call in response.tool_calls
                    ]
                    high_risk_tools = set(state.get("high_risk_tools") or set())
                    high_risk_calls = [
                        call for call in tool_calls if call["name"] in high_risk_tools
                    ]
                    if len(high_risk_calls) > 1:
                        emit(AssistantText(delta=_MULTI_HIGH_RISK_MSG))
                        messages = [
                            *list(state.get("messages") or []),
                            AIMessage(content=_MULTI_HIGH_RISK_MSG),
                        ]
                        return {
                            "messages": messages,
                            "queued_tool_calls": [],
                            "loop_count": loop_count,
                            "route": "finalize",
                        }

                    _emit_model_messages([response], emit)
                    messages = [*list(state.get("messages") or []), response]
                    return {
                        "messages": messages,
                        "queued_tool_calls": tool_calls,
                        "loop_count": loop_count,
                        "route": "tool_policy_gate" if tool_calls else "finalize",
                    }

                async def tool_policy_gate_node(state: dict[str, Any]) -> dict[str, Any]:
                    queue_items = list(state.get("queued_tool_calls") or [])
                    if not queue_items:
                        return {"route": "reasoning"}
                    active = queue_items[0]
                    remaining = queue_items[1:]
                    visible_names = {
                        str(getattr(tool, "name", ""))
                        for tool in list(state.get("model_visible_tools") or [])
                    }
                    name = str(active.get("name") or "")
                    if name not in visible_names:
                        msg = f"{name} is not available from MCP tools"
                        emit(AssistantText(delta=msg))
                        return {
                            "messages": append_tool_message(
                                state,
                                active,
                                msg,
                                is_error=True,
                            ),
                            "queued_tool_calls": remaining,
                            "active_tool_call": {},
                            "route": "tool_policy_gate" if remaining else "reasoning",
                        }
                    return {
                        "active_tool_call": active,
                        "queued_tool_calls": remaining,
                        "route": "tool_call",
                    }

                async def tool_call_node(state: dict[str, Any]) -> dict[str, Any]:
                    active = dict(state.get("active_tool_call") or {})
                    name = str(active.get("name") or "")
                    args = dict(active.get("args") or {})
                    tool = dict(state.get("mcp_tools_by_name") or {}).get(name)
                    if tool is None:
                        msg = f"{name} is not available from MCP tools"
                        emit(AssistantText(delta=msg))
                        return {
                            "messages": append_tool_message(state, active, msg, is_error=True),
                            "route": "reasoning",
                        }
                    emit(ToolCall(name=name, input=args))
                    try:
                        result = await invoke_mcp_tool(
                            tool,
                            args,
                            runtime_args_for_state(state),
                        )
                    except Exception as err:
                        output = {"status": "error", "result": str(err)}
                        emit(ToolResult(name=name, output=output))
                        return {
                            "messages": append_tool_message(
                                state,
                                active,
                                output,
                                is_error=True,
                            ),
                            "route": "reasoning",
                        }
                    emit(ToolResult(name=name, output=result))
                    if isinstance(result, dict) and result.get("status") == "pending_confirmation":
                        return {
                            "pending_action": result["pending_action"],
                            "pending_tool_call": active,
                            "route": "human_approval",
                        }
                    queued = list(state.get("queued_tool_calls") or [])
                    return {
                        "messages": append_tool_message(state, active, result),
                        "active_tool_call": {},
                        "route": "tool_policy_gate" if queued else "reasoning",
                    }

                async def human_approval_node(state: dict[str, Any]) -> dict[str, Any]:
                    action = dict(state.get("pending_action") or {})
                    if not action:
                        return {"route": "finalize"}
                    decision = await decision_for_pending(action)
                    if decision.get("decision") != "approve":
                        output = {"status": "ok", "result": f"denied {action.get('tool')}"}
                        return {
                            "approval_decision": decision,
                            "messages": append_tool_message(
                                state,
                                state.get("pending_tool_call"),
                                output,
                            ),
                            "pending_action": {},
                            "route": "reasoning" if state.get("pending_tool_call") else "finalize",
                        }
                    return {"approval_decision": decision, "route": "deploy"}

                async def deploy_node(state: dict[str, Any]) -> dict[str, Any]:
                    action = dict(state.get("pending_action") or {})
                    if not action:
                        return {"route": "finalize"}
                    caps = dict(state.get("capabilities") or {})
                    tools_by_name = dict(state.get("mcp_tools_by_name") or {})
                    commit_name = mcp_commit_tool_name(action, caps)
                    commit_tool = tools_by_name.get(commit_name)
                    if commit_tool is None:
                        output = {
                            "status": "error",
                            "result": f"{commit_name} is not available from MCP tools",
                        }
                        emit(AssistantText(delta=str(output["result"])))
                        return {
                            "messages": append_tool_message(
                                state,
                                state.get("pending_tool_call"),
                                output,
                                is_error=True,
                            ),
                            "route": "reasoning" if state.get("pending_tool_call") else "finalize",
                        }
                    decision = dict(state.get("approval_decision") or {})
                    commit_input = {
                        "pending_action_id": action["id"],
                        "session_id": params.ctx.session_id
                        or action.get("session_id")
                        or "default",
                        "cwd": params.ctx.cwd,
                        "decision": decision.get("decision", "deny"),
                        "typed_phrase": decision.get("typed_phrase"),
                        "secrets": decision.get("secrets"),
                    }
                    emit(ToolCall(name=commit_name, input=commit_input))
                    result = await commit_tool.ainvoke(commit_input)
                    payload = _coerce_mcp_payload(result) or result
                    emit(ToolResult(name=commit_name, output=payload))
                    if isinstance(payload, dict) and payload.get("rollback_action"):
                        return {
                            "deploy_result": payload,
                            "rollback_action": payload["rollback_action"],
                            "route": "rollback",
                        }
                    return {
                        "deploy_result": payload
                        if isinstance(payload, dict)
                        else {"result": payload},
                        "messages": append_tool_message(
                            state,
                            state.get("pending_tool_call"),
                            payload,
                        ),
                        "pending_action": {},
                        "route": "reasoning" if state.get("pending_tool_call") else "finalize",
                    }

                async def rollback_node(state: dict[str, Any]) -> dict[str, Any]:
                    action = dict(state.get("rollback_action") or {})
                    if not action:
                        return {"route": "finalize"}
                    caps = dict(state.get("capabilities") or {})
                    tools_by_name = dict(state.get("mcp_tools_by_name") or {})
                    tool_name = mcp_rollback_tool_name({"rollback_action": action}, caps)
                    rollback_tool = tools_by_name.get(tool_name)
                    if rollback_tool is None:
                        output = {
                            "status": "error",
                            "result": f"{tool_name} is not available from MCP tools",
                        }
                        emit(AssistantText(delta=str(output["result"])))
                        return {
                            "messages": append_tool_message(
                                state,
                                state.get("pending_tool_call"),
                                output,
                                is_error=True,
                            ),
                            "route": "reasoning" if state.get("pending_tool_call") else "finalize",
                        }
                    rollback_input = {
                        "rollback_action_id": action["id"],
                        "session_id": params.ctx.session_id or "default",
                        "cwd": params.ctx.cwd,
                    }
                    emit(ToolCall(name=tool_name, input=rollback_input))
                    result = await rollback_tool.ainvoke(rollback_input)
                    payload = _coerce_mcp_payload(result) or result
                    emit(ToolResult(name=tool_name, output=payload))
                    return {
                        "rollback_result": payload
                        if isinstance(payload, dict)
                        else {"result": payload},
                        "messages": append_tool_message(
                            state,
                            state.get("pending_tool_call"),
                            payload,
                        ),
                        "route": "reasoning" if state.get("pending_tool_call") else "finalize",
                    }

                async def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
                    final_messages = state.get("messages")
                    if final_messages:
                        converted = [
                            converted
                            for msg in final_messages
                            if (converted := _from_langchain_message(msg)) is not None
                        ]
                        params.messages[:] = converted
                    return {"finalized": True, "route": "finalize"}

                graph = build_langgraph_runtime_graph(
                    context_loader_node=context_loader_node,
                    command_router_node=command_router_node,
                    reasoning_node=reasoning_node,
                    tool_policy_gate_node=tool_policy_gate_node,
                    tool_call_node=tool_call_node,
                    human_approval_node=human_approval_node,
                    deploy_node=deploy_node,
                    rollback_node=rollback_node,
                    finalize_node=finalize_node,
                )
                await graph.ainvoke({"handled": False})
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


__all__ = ["RuntimeLangGraphBackend"]

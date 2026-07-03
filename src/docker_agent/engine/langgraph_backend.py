"""LangGraphBackend orchestrator using native LangChain tool calling."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from docker_agent.agent import AgentBackend, BackendQueryParams
from docker_agent.config import load_user_config
from docker_agent.core.iteration_limits import derive_recursion_limit
from docker_agent.core.prompt_builder import build_system_prompt
from docker_agent.engine.adapters.tool_adapter import run_tool
from docker_agent.engine.langchain_model_factory import create_chat_model
from docker_agent.policy.defaults import ensure_global_policy
from docker_agent.policy.policy_engine import PolicyEngine
from docker_agent.tools.destroy_all_stacks import destroy_all_stacks
from docker_agent.tools.destroy_stack import destroy_stack
from docker_agent.tools.stop_stack import stop_stack
from docker_agent.tools.langchain_registry import get_langchain_tools, high_risk_tool_names
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

_MULTI_HIGH_RISK_MSG = (
    "Only one high-risk tool may be called per turn. Call them one at a time."
)


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
                        resp = await params.ctx.request_permission("destroy_stack", input_data)
                        if permission_kind(resp) == "deny":
                            emit(AssistantText(delta="destroy_stack aborted: permission denied"))
                            return
                        if permission_kind(resp) == "always_allow_in_session":
                            params.ctx.allow_set.add("destroy_stack")
                    await _run_tool_events(destroy_stack, input_data, params.ctx, emit)
                    return

                direct_stop = (
                    _parse_direct_stop_stack(last_user.content)
                    if last_user is not None
                    else None
                )
                if direct_stop is not None:
                    input_data = stop_stack.input_schema.model_validate(
                        {
                            "stack_name": direct_stop["stack_name"],
                            **(
                                {"services": direct_stop["services"]}
                                if direct_stop.get("services")
                                else {}
                            ),
                        }
                    )
                    if "stop_stack" not in params.ctx.allow_set:
                        resp = await params.ctx.request_permission("stop_stack", input_data)
                        if permission_kind(resp) == "deny":
                            emit(AssistantText(delta="stop_stack aborted: permission denied"))
                            return
                        if permission_kind(resp) == "always_allow_in_session":
                            params.ctx.allow_set.add("stop_stack")
                    await _run_tool_events(stop_stack, input_data, params.ctx, emit)
                    return

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

                tools = get_langchain_tools()

                agent = create_agent(
                    model=chat_model,
                    tools=tools,
                    system_prompt=build_system_prompt(params.ctx.state_store.summary()),
                    context_schema=dict,
                    checkpointer=MemorySaver(),
                    middleware=[HighRiskToolCallMiddleware(high_risk_tool_names(tools))],
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
                    "messages": [_to_langchain_message(m) for m in messages]
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
                final_messages = (
                    final_values.get("messages")
                    if isinstance(final_values, dict)
                    else None
                )
                if final_messages is not None:
                    converted = [
                        converted
                        for msg in final_messages
                        if (converted := _from_langchain_message(msg)) is not None
                    ]
                    params.messages[:] = converted
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


__all__ = ["LangGraphBackend"]

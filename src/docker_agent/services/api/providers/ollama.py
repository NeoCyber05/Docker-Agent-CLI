"""Ollama provider adapter.

Parity: ``src/services/api/providers/ollama.ts``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

from docker_agent.services.api._message_utils import (
    block_attr,
    block_type,
    build_tool_use_to_name,
    message_role,
)
from docker_agent.services.api.tool_schema import to_openai_function
from docker_agent.services.api.types import (
    CallModelParams,
    ErrorEvent,
    MessageStopEvent,
    ProviderEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
    UsageEvent,
)
from docker_agent.utils.sync_bridge import aiter_in_thread


def _build_ollama_messages(messages: list[Any], *, system: str) -> list[dict[str, Any]]:
    tool_use_to_name = build_tool_use_to_name(messages)
    result: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        role = message_role(message)
        if role == "user":
            result.append({"role": "user", "content": getattr(message, "content", "")})
        elif role == "assistant":
            content = getattr(message, "content", None) or []
            text = "".join(
                block_attr(b, "text", "") for b in content if block_type(b) == "text"
            )
            tool_calls = [
                {
                    "function": {
                        "name": block_attr(b, "name", ""),
                        "arguments": block_attr(b, "input", {}),
                    }
                }
                for b in content
                if block_type(b) == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            result.append(msg)
        elif role == "tool":
            tool_use_id = getattr(message, "tool_use_id", None) or block_attr(
                message, "toolUseId", ""
            )
            result.append(
                {
                    "role": "tool",
                    "name": tool_use_to_name.get(tool_use_id, tool_use_id),
                    "content": getattr(message, "content", ""),
                }
            )
    return result


class OllamaProvider:
    name = "ollama"

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = env or dict(os.environ)

    @property
    def host(self) -> str:
        return self._env.get("OLLAMA_HOST") or "http://localhost:11434"

    async def list_models(self) -> list[str]:
        import asyncio

        from ollama import Client

        client = Client(host=self.host)

        def _list_sync() -> list[str]:
            res = client.list()
            names: list[str] = []
            for m in res.models:
                model_name = getattr(m, "model", None) or getattr(m, "name", None)
                if model_name:
                    names.append(model_name)
            return sorted(names)

        return await asyncio.to_thread(_list_sync)

    async def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]:
        from ollama import Client

        host = self.host
        model = params.model or self._env.get("OLLAMA_MODEL") or "qwen2.5:14b"
        client = Client(host=host)
        tool_defs = [
            {"type": "function", "function": to_openai_function(t)["function"]}
            for t in params.tools
        ]
        messages = _build_ollama_messages(params.messages, system=params.system)

        def sync_stream() -> Iterator[ProviderEvent]:
            try:
                stream = client.chat(
                    model=model,
                    messages=messages,
                    stream=True,
                    tools=tool_defs or None,
                )
                output_tokens = 0
                tool_call_idx = 0
                for part in stream:
                    content = getattr(part, "message", None) and getattr(
                        part.message, "content", None
                    )
                    if content:
                        yield TextDeltaEvent(text=content)
                    calls = getattr(getattr(part, "message", None), "tool_calls", None)
                    if calls:
                        for c in calls:
                            call_id = f"ollama-{tool_call_idx}"
                            tool_call_idx += 1
                            yield ToolUseStartEvent(id=call_id, name=c.function.name)
                            yield ToolUseDeltaEvent(
                                id=call_id,
                                args_partial_json=json.dumps(c.function.arguments),
                            )
                            yield ToolUseStopEvent(id=call_id)
                    eval_count = getattr(part, "eval_count", None)
                    if eval_count is not None:
                        output_tokens = eval_count

                yield UsageEvent(input_tokens=0, output_tokens=output_tokens)
                yield MessageStopEvent(stop_reason="end_turn")
            except Exception as err:  # noqa: BLE001 - surfaced as an event
                yield ErrorEvent(error=err)

        async for event in aiter_in_thread(sync_stream):
            yield event
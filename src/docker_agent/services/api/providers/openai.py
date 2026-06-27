"""OpenAI provider adapter.

Parity: ``src/services/api/providers/openai.ts``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

from docker_agent.services.api._message_utils import build_openai_chat_messages
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
from docker_agent.vault.api_key_store import ApiKeyStore, resolve_stored_api_key


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        env: dict[str, str] | None = None,
        api_key_store: ApiKeyStore | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self._env = env or dict(os.environ)
        self._api_key_store = api_key_store
        self._client = client

    def _make_client(self, api_key: str) -> Any:
        if self._client is not None:
            return self._client
        from openai import OpenAI

        return OpenAI(
            api_key=api_key,
            base_url=self._env.get("OPENAI_BASE_URL") or None,
        )

    async def list_models(self) -> list[str]:
        import asyncio

        api_key = await resolve_stored_api_key("openai", self._env, self._api_key_store)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = self._make_client(api_key)
        res = await asyncio.to_thread(client.models.list)
        return sorted(
            m.id for m in res.data if isinstance(getattr(m, "id", None), str) and m.id
        )

    async def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]:
        api_key = await resolve_stored_api_key("openai", self._env, self._api_key_store)
        if not api_key:
            yield ErrorEvent(error=RuntimeError("OPENAI_API_KEY not set"))
            return

        client = self._make_client(api_key)
        model = params.model or self._env.get("OPENAI_MODEL") or "gpt-4o-mini"
        tool_defs = [to_openai_function(t) for t in params.tools]
        messages = build_openai_chat_messages(params.messages, system=params.system)

        def sync_stream() -> Iterator[ProviderEvent]:
            try:
                stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tool_defs or None,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                tool_buffers: dict[int, dict[str, str]] = {}
                input_tokens = 0
                output_tokens = 0
                stop_reason: str = "end_turn"
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    if delta.content:
                        yield TextDeltaEvent(text=delta.content)
                    for call in delta.tool_calls or []:
                        idx = call.index
                        buf = tool_buffers.get(idx)
                        if buf is None:
                            buf = {
                                "id": call.id or f"oa-{idx}",
                                "name": call.function.name or "",
                                "args": "",
                            }
                            tool_buffers[idx] = buf
                            yield ToolUseStartEvent(id=buf["id"], name=buf["name"])
                        if call.function.arguments:
                            buf["args"] += call.function.arguments
                            yield ToolUseDeltaEvent(
                                id=buf["id"], args_partial_json=call.function.arguments
                            )
                    finish = chunk.choices[0].finish_reason if chunk.choices else None
                    if finish == "tool_calls":
                        for buf in tool_buffers.values():
                            yield ToolUseStopEvent(id=buf["id"])
                        stop_reason = "tool_use"
                    if finish == "length":
                        stop_reason = "max_tokens"
                    if chunk.usage:
                        input_tokens = chunk.usage.prompt_tokens or input_tokens
                        output_tokens = chunk.usage.completion_tokens or output_tokens

                yield UsageEvent(input_tokens=input_tokens, output_tokens=output_tokens)
                yield MessageStopEvent(stop_reason=stop_reason)
            except Exception as err:  # noqa: BLE001 - surfaced as an event
                yield ErrorEvent(error=err)

        async for event in aiter_in_thread(sync_stream):
            yield event
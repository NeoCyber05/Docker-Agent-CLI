"""Gemini provider adapter.

Parity: ``src/services/api/providers/gemini.ts``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from infra_agent.services.api._message_utils import (
    block_attr,
    block_type,
    build_tool_use_to_name,
    message_role,
)
from infra_agent.services.api.tool_schema import to_gemini_function_declaration
from infra_agent.services.api.types import (
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
from infra_agent.utils.sync_bridge import aiter_in_thread
from infra_agent.vault.api_key_store import ApiKeyStore, resolve_stored_api_key


def _build_gemini_contents(messages: list[Any]) -> list[dict[str, Any]]:
    tool_use_to_name = build_tool_use_to_name(messages)
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message_role(message)
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": getattr(message, "content", "")}]})
        elif role == "assistant":
            parts: list[dict[str, Any]] = []
            for block in getattr(message, "content", None) or []:
                if block_type(block) == "text":
                    parts.append({"text": block_attr(block, "text", "")})
                elif block_type(block) == "tool_use":
                    parts.append(
                        {
                            "function_call": {
                                "name": block_attr(block, "name", ""),
                                "args": block_attr(block, "input", {}),
                            }
                        }
                    )
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            tool_use_id = getattr(message, "tool_use_id", None) or block_attr(
                message, "toolUseId", ""
            )
            contents.append(
                {
                    "role": "function",
                    "parts": [
                        {
                            "function_response": {
                                "name": tool_use_to_name.get(tool_use_id, tool_use_id),
                                "response": {"content": getattr(message, "content", "")},
                            }
                        }
                    ],
                }
            )
    return contents


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        env: dict[str, str] | None = None,
        api_key_store: ApiKeyStore | None = None,
    ) -> None:
        self._env = env or dict(os.environ)
        self._api_key_store = api_key_store

    async def list_models(self) -> list[str]:
        api_key = await resolve_stored_api_key("gemini", self._env, self._api_key_store)
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch models: {res.text}")
        data = res.json()
        return sorted(
            m["name"].replace("models/", "")
            for m in data.get("models", [])
            if "gemini" in m.get("name", "")
        )

    async def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]:
        import google.generativeai as genai

        api_key = await resolve_stored_api_key("gemini", self._env, self._api_key_store)
        if not api_key:
            yield ErrorEvent(error=RuntimeError("GEMINI_API_KEY not set"))
            return

        model_id = params.model or self._env.get("GEMINI_MODEL") or "gemini-2.0-flash"
        genai.configure(api_key=api_key)  # type: ignore[attr-defined]
        tools = params.tools
        tool_config = None
        if tools:
            tool_config = [
                {
                    "function_declarations": [
                        to_gemini_function_declaration(t) for t in tools
                    ]
                }
            ]
        model = genai.GenerativeModel(  # type: ignore[attr-defined]
            model_id,
            system_instruction=params.system,
            tools=tool_config,
        )
        contents = _build_gemini_contents(params.messages)

        def sync_stream() -> Iterator[ProviderEvent]:
            try:
                result = model.generate_content(contents, stream=True)
                input_tokens = 0
                output_tokens = 0
                tool_call_idx = 0
                has_output = False
                last_finish_reason: str | None = None
                for chunk in result:
                    pf = getattr(chunk, "prompt_feedback", None)
                    block_reason = getattr(pf, "block_reason", None) if pf else None
                    if block_reason:
                        yield ErrorEvent(
                            error=RuntimeError(
                                f"Prompt blocked by Gemini safety filter: {block_reason}"
                            )
                        )
                        return

                    for cand in getattr(chunk, "candidates", []) or []:
                        if getattr(cand, "finish_reason", None):
                            last_finish_reason = str(cand.finish_reason)
                        for part in getattr(getattr(cand, "content", None), "parts", []) or []:
                            if getattr(part, "thought", False) and not getattr(
                                part, "function_call", None
                            ):
                                continue
                            text = getattr(part, "text", None)
                            if text:
                                has_output = True
                                yield TextDeltaEvent(text=text)
                            fc = getattr(part, "function_call", None)
                            if fc:
                                has_output = True
                                call_id = f"gemini-{tool_call_idx}"
                                tool_call_idx += 1
                                yield ToolUseStartEvent(id=call_id, name=fc.name)
                                yield ToolUseDeltaEvent(
                                    id=call_id, args_partial_json=json.dumps(dict(fc.args))
                                )
                                yield ToolUseStopEvent(id=call_id)

                    usage = getattr(chunk, "usage_metadata", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_token_count", input_tokens)
                        output_tokens = getattr(
                            usage, "candidates_token_count", output_tokens
                        )

                if (
                    last_finish_reason
                    and last_finish_reason not in ("STOP", "MAX_TOKENS")
                    and not has_output
                ):
                    yield ErrorEvent(
                        error=RuntimeError(
                            f"Gemini response ended with reason: {last_finish_reason}"
                        )
                    )
                    return
                if not has_output:
                    yield ErrorEvent(
                        error=RuntimeError(
                            f'Gemini returned an empty response for model "{model_id}".'
                        )
                    )
                    return

                yield UsageEvent(input_tokens=input_tokens, output_tokens=output_tokens)
                yield MessageStopEvent(stop_reason="end_turn")
            except Exception as err:  # noqa: BLE001 - surfaced as an event
                yield ErrorEvent(error=err)

        async for event in aiter_in_thread(sync_stream):
            yield event
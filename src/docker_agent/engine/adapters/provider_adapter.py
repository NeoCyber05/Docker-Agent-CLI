"""Drive a Provider stream and collect a structured turn."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from docker_agent.core.prompt_builder import build_system_prompt
from docker_agent.services.api.types import (
    CallModelParams,
    ErrorEvent,
    MessageStopEvent,
    Provider,
    TextDeltaEvent,
    ToolSchema,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
    UsageEvent,
)
from docker_agent.types.message import Message


@dataclass
class ProviderTurn:
    text: str = ""
    tool_uses: list[dict[str, str]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict[str, int] | None = None


@dataclass
class StreamedEvent:
    type: str
    text: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: Exception | None = None


async def drive_provider(
    *,
    provider: Provider,
    messages: list[Message],
    ctx: Any,
    model: str | None = None,
    on_event: Callable[[StreamedEvent], None],
    signal: Any | None = None,
    tools: list[Any] | None = None,
) -> ProviderTurn:
    del ctx
    available_tools = tools or []
    params = CallModelParams(
        messages=messages,
        tools=[
            ToolSchema(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in available_tools
        ],
        system=build_system_prompt(""),
        model=model,
    )

    turn = ProviderTurn()
    async for ev in provider.stream(params):
        if signal is not None and getattr(signal, "is_set", lambda: False)():
            return turn
        if isinstance(ev, TextDeltaEvent):
            turn.text += ev.text
            on_event(StreamedEvent(type="assistant_text", text=ev.text))
        elif isinstance(ev, ToolUseStartEvent):
            turn.tool_uses.append({"id": ev.id, "name": ev.name, "args_partial": ""})
        elif isinstance(ev, ToolUseDeltaEvent):
            for use in turn.tool_uses:
                if use["id"] == ev.id:
                    use["args_partial"] += ev.args_partial_json
        elif isinstance(ev, ToolUseStopEvent):
            pass
        elif isinstance(ev, MessageStopEvent):
            turn.stop_reason = ev.stop_reason
        elif isinstance(ev, UsageEvent):
            turn.usage = {"input_tokens": ev.input_tokens, "output_tokens": ev.output_tokens}
            on_event(
                StreamedEvent(
                    type="usage",
                    input_tokens=ev.input_tokens,
                    output_tokens=ev.output_tokens,
                )
            )
        elif isinstance(ev, ErrorEvent):
            on_event(StreamedEvent(type="error", error=ev.error))
            return turn
    return turn


__all__ = ["ProviderTurn", "StreamedEvent", "drive_provider"]

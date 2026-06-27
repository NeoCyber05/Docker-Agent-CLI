"""Agent node: call provider, emit events, return assistant message.

Parity: ``src/backend/langgraph/nodes/agentNode.ts``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docker_agent.backend.langgraph.adapters.provider_adapter import drive_provider
from docker_agent.backend.langgraph.state import AgentState
from docker_agent.services.api.types import Provider
from docker_agent.types.events import AssistantText, Error, IterationStart, Usage
from docker_agent.types.message import AssistantBlock, AssistantMessage

MAX_ITERATIONS = 24


@dataclass
class AgentNodeDeps:
    provider: Provider
    ctx: Any
    emit: Callable[[Any], None]
    model: str | None = None


async def agent_node(deps: AgentNodeDeps, state: AgentState) -> dict[str, Any]:
    if state.iter >= MAX_ITERATIONS:
        deps.emit(
            Error(error=RuntimeError(f"agent loop reached max iterations ({MAX_ITERATIONS})"))
        )
        return {"iter": state.iter}

    deps.emit(IterationStart(n=state.iter + 1))

    def on_event(ev: Any) -> None:
        if ev.type == "assistant_text" and ev.text:
            deps.emit(AssistantText(delta=ev.text))
        elif ev.type == "usage":
            deps.emit(
                Usage(
                    inputTokens=ev.input_tokens or 0,
                    outputTokens=ev.output_tokens or 0,
                )
            )
        elif ev.type == "error":
            deps.emit(Error(error=ev.error))

    turn = await drive_provider(
        provider=deps.provider,
        messages=state.messages,
        ctx=deps.ctx,
        model=deps.model,
        on_event=on_event,
        signal=deps.ctx.abort_signal,
    )

    blocks: list[Any] = []
    if turn.text:
        blocks.append(AssistantBlock.model_validate({"type": "text", "text": turn.text}))
    for tu in turn.tool_uses:
        try:
            input_data = json.loads(tu["args_partial"] or "{}")
        except Exception:
            input_data = {}
        blocks.append(
            AssistantBlock.model_validate(
                {"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": input_data}
            )
        )

    if turn.stop_reason == "max_tokens":
        deps.emit(Error(error=RuntimeError("provider response stopped: max tokens reached")))

    return {
        "messages": [AssistantMessage(content=blocks)],
        "iter": state.iter + 1,
    }
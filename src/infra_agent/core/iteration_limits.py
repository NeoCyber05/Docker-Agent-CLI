"""Agent loop iteration budget and graceful limit handling."""

from __future__ import annotations

import os
from typing import Any

from infra_agent.types.message import Message

_DEFAULT_MAX_ITERATIONS = 24


def _read_max_iterations() -> int:
    raw = os.environ.get("DOCKER_AGENT_MAX_ITER", str(_DEFAULT_MAX_ITERATIONS))
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_ITERATIONS


MAX_ITERATIONS = _read_max_iterations()


def derive_recursion_limit(max_iterations: int | None = None) -> int:
    """LangGraph super-step budget: agent + special nodes + tools per iteration."""
    limit = max_iterations if max_iterations is not None else MAX_ITERATIONS
    return limit * 3 + 10


def _block_type(block: Any) -> str | None:
    return getattr(block, "type", None)


def build_graceful_summary(messages: list[Message], max_iterations: int) -> str:
    """Summarize completed tool steps when the iteration budget is exhausted."""
    tool_names_by_id: dict[str, str] = {}
    completed_steps: list[str] = []

    for msg in messages:
        if msg.role == "assistant":
            for block in msg.content:
                if _block_type(block) == "tool_use":
                    tool_names_by_id[block.id] = block.name
        elif msg.role == "tool":
            name = tool_names_by_id.get(msg.tool_use_id, "tool")
            status = "failed" if msg.is_error else "ok"
            completed_steps.append(f"{name} ({status})")

    if completed_steps:
        steps_text = "\n".join(f"  - {step}" for step in completed_steps)
        completed_block = f"Các bước đã thực hiện:\n{steps_text}"
    else:
        completed_block = "Chưa có tool call nào hoàn thành trong session này."

    return (
        f"Agent đã dùng hết {max_iterations} iterations.\n\n"
        f"{completed_block}\n\n"
        f"Bước tiếp theo có thể là: tiếp tục task từ điểm dừng hiện tại.\n\n"
        'Gõ "tiếp tục" để chạy thêm hoặc đặt câu hỏi follow-up.'
    )


__all__ = [
    "MAX_ITERATIONS",
    "build_graceful_summary",
    "derive_recursion_limit",
]

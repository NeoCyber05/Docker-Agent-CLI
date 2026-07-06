"""Tests for iteration_limits helpers."""

from docker_agent.core.iteration_limits import (
    MAX_ITERATIONS,
    build_graceful_summary,
    derive_recursion_limit,
)
from docker_agent.types.message import ToolResultMessage, UserMessage


def test_derive_recursion_limit_scales_with_max_iterations() -> None:
    assert derive_recursion_limit(24) == 82
    assert derive_recursion_limit() == MAX_ITERATIONS * 3 + 10


def test_build_graceful_summary_lists_tool_steps() -> None:
    messages = [
        UserMessage(content="hi"),
        ToolResultMessage(toolUseId="t1", content="done", isError=False),
    ]
    summary = build_graceful_summary(messages, 24)
    assert "\u0111\u00e3 d\u00f9ng h\u1ebft 24 iterations" in summary
    assert "tool (ok)" in summary


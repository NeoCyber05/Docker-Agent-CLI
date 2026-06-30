"""Core orchestration primitives - context, limits, and prompt construction."""

from docker_agent.core.iteration_limits import (
    MAX_ITERATIONS,
    build_graceful_summary,
    derive_recursion_limit,
)
from docker_agent.core.loop_context import LoopContext, PlanReadyPayload
from docker_agent.core.prompt_builder import build_system_prompt

__all__ = [
    "LoopContext",
    "MAX_ITERATIONS",
    "PlanReadyPayload",
    "build_graceful_summary",
    "build_system_prompt",
    "derive_recursion_limit",
]
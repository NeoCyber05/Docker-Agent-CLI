"""Public LangGraph backend wrapper."""

from __future__ import annotations

from docker_agent.engine.langgraph.runtime import RuntimeLangGraphBackend


class LangGraphBackend(RuntimeLangGraphBackend):
    """Thin public backend class for the LangGraph runtime."""


__all__ = ["LangGraphBackend"]
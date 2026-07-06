"""Formatting helpers for Docker MCP tool results."""

from __future__ import annotations

from typing import Any


def format_plan_blocker(result: Any) -> str:
    """Render plan validation blockers in a compact model-readable form."""
    issues = getattr(result, "issues", None) or []
    if not issues:
        reason = getattr(result, "reason", None)
        return str(reason or "Plan is blocked.")
    lines = ["Plan is blocked:"]
    for issue in issues:
        severity = getattr(issue, "severity", None) or getattr(issue, "kind", None) or "issue"
        message = getattr(issue, "message", None) or str(issue)
        service = getattr(issue, "service", None)
        prefix = f"[{service}] " if service else ""
        lines.append(f"- {severity}: {prefix}{message}")
    return "\n".join(lines)


__all__ = ["format_plan_blocker"]


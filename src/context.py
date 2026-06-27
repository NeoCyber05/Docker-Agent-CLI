"""System prompt builder.

Parity: ``src/context.ts``.
"""

from __future__ import annotations

import importlib.resources


def build_system_prompt(state_summary: str) -> str:
    template = importlib.resources.files("src.prompts").joinpath("react.md").read_text(
        encoding="utf-8"
    )
    return template.replace("{{STATE_SUMMARY}}", state_summary.strip() or "(none)")
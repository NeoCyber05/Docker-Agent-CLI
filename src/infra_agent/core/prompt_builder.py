"""System prompt builder.
"""

from __future__ import annotations

import importlib.resources


def build_system_prompt(state_summary: str, plugin_instructions: str = "") -> str:
    template = importlib.resources.files("infra_agent.prompts").joinpath("react.md").read_text(
        encoding="utf-8"
    )
    rendered = template.replace(
        "{{PLUGIN_INSTRUCTIONS}}",
        plugin_instructions.strip() or "(No infrastructure plugins are currently connected.)",
    )
    return rendered.replace("{{STATE_SUMMARY}}", state_summary.strip() or "(none)")
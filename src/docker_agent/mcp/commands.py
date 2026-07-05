"""Generic command router driven by plugin metadata."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConfirmationKind = Literal[
    "none",
    "permission",
    "typed",
    "secrets_input",
    "plan_review",
]


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str
    tool: str
    confirmation: ConfirmationKind = "none"
    args: dict[str, Any] = Field(default_factory=dict)
    split_args: dict[str, str] = Field(default_factory=dict)
    phrase_template: str | None = None
    reason_template: str | None = None


class CommandMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    input: dict[str, Any]
    confirmation: ConfirmationKind
    phrase: str | None = None
    reason: str | None = None


def _expand_arg(value: Any, groups: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return groups.get(value[1:])
    return value


def _split_arg(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [part.strip() for part in re.split(r"[,\s]+", value) if part.strip()]
    return parts or None


def match_command(content: str, specs: list[CommandSpec]) -> CommandMatch | None:
    trimmed = content.strip()
    for spec in specs:
        match = re.match(spec.pattern, trimmed, re.IGNORECASE)
        if match is None:
            continue
        groups = {key: value for key, value in match.groupdict().items() if value is not None}
        input_data = {
            key: value
            for key, raw_value in spec.args.items()
            if (value := _expand_arg(raw_value, groups)) is not None
        }
        for key, group_name in spec.split_args.items():
            split = _split_arg(groups.get(group_name))
            if split is not None:
                input_data[key] = split
        return CommandMatch(
            tool=spec.tool,
            input=input_data,
            confirmation=spec.confirmation,
            phrase=(
                spec.phrase_template.format(**groups)
                if spec.phrase_template is not None
                else None
            ),
            reason=(
                spec.reason_template.format(**groups)
                if spec.reason_template is not None
                else None
            ),
        )
    return None


__all__ = ["CommandMatch", "CommandSpec", "ConfirmationKind", "match_command"]

"""Slash command dispatch helpers.

Parity: ``src/slashDispatch.ts``.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Literal, TypedDict

import yaml

from docker_agent.state.secret_redactor import should_redact
from docker_agent.state.state_store import StateStore
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.types.stack import StackDefinition, StackSummary


@dataclass
class SlashDispatchContext:
    cwd: str
    state_store: StateStore


class DirectSlashOk(TypedDict):
    ok: Literal[True]
    text: str


class DirectSlashErr(TypedDict):
    ok: Literal[False]
    error: str


DirectSlashResult = DirectSlashOk | DirectSlashErr


def format_stacks_table(stacks: list[StackSummary]) -> str:
    if not stacks:
        return "**Managed stacks**\n\nNo stacks defined under `.docker-agent/states/`."
    header = "| Name | Services | Last applied |"
    sep = "| --- | --- | --- |"
    rows = [
        f"| {s.name} | {s.service_count} | {s.last_applied or 'never'} |"
        for s in stacks
    ]
    return "\n".join(["**Managed stacks**", "", header, sep, *rows])


def _redact_stack_for_display(definition: StackDefinition) -> StackDefinition:
    clone = copy.deepcopy(definition)
    for spec in clone.services.values():
        if not spec.environment:
            continue
        for key in list(spec.environment.keys()):
            if should_redact(key):
                spec.environment[key] = "***"
    return clone


def dispatch_stacks(ctx: SlashDispatchContext) -> str:
    return format_stacks_table(ctx.state_store.list())


def dispatch_yaml(stack_name: str, ctx: SlashDispatchContext) -> DirectSlashResult:
    definition = ctx.state_store.read(stack_name)
    if definition is None:
        return {"ok": False, "error": f"stack {stack_name} not found"}
    redacted = _redact_stack_for_display(definition)
    data = redacted.model_dump(by_alias=True, exclude_none=True)
    text = yaml.safe_dump(data, sort_keys=False)
    return {"ok": True, "text": f"```yaml\n{text.strip()}\n```"}


def destroy_stack_prompt(stack_name: str, remove_volumes: bool = False) -> str:
    suffix = " with volumes" if remove_volumes else ""
    return f"Destroy stack {stack_name}{suffix}"


def is_destroy_all_prompt(content: str) -> bool:
    return content.strip().lower() == "destroy all stacks"


def parse_direct_destroy_stack(content: str) -> dict[str, str | bool] | None:
    trimmed = content.strip()
    patterns = [
        re.compile(r"^Destroy stack (\S+)(?:\s+with volumes)?$", re.IGNORECASE),
        re.compile(r"^destroy (\S+)(?:\s+with volumes)?$", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.match(trimmed)
        if not match or not match.group(1) or match.group(1).lower() == "all":
            continue
        return {
            "stack_name": match.group(1),
            "remove_volumes": bool(re.search(r"\swith volumes$", trimmed, re.IGNORECASE)),
        }
    return None


def dispatch_secrets_list(stack_name: str, ctx: SlashDispatchContext) -> DirectSlashResult:
    definition = ctx.state_store.read(stack_name)
    if definition is None:
        return {"ok": False, "error": f"stack {stack_name} not found"}
    keys_ctx = SecretKeysContext(cwd=ctx.cwd, state_store=ctx.state_store)
    keys = sorted(collect_secret_keys(stack_name, keys_ctx))
    if not keys:
        return {"ok": True, "text": f"No secret keys tracked for stack **{stack_name}**."}
    lines = [f"Secret keys for **{stack_name}**:"]
    lines.extend(f"- {key}" for key in keys)
    return {"ok": True, "text": "\n".join(lines)}


__all__ = [
    "DirectSlashResult",
    "SlashDispatchContext",
    "destroy_stack_prompt",
    "dispatch_secrets_list",
    "dispatch_stacks",
    "dispatch_yaml",
    "format_stacks_table",
    "is_destroy_all_prompt",
    "parse_direct_destroy_stack",
]
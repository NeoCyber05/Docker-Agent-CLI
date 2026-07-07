"""Slash command prompt helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypedDict


@dataclass
class SlashDispatchContext:
    cwd: str


class DirectSlashOk(TypedDict):
    ok: Literal[True]
    text: str


class DirectSlashErr(TypedDict):
    ok: Literal[False]
    error: str


DirectSlashResult = DirectSlashOk | DirectSlashErr


def dispatch_stacks(_ctx: SlashDispatchContext) -> str:
    return "Use the agent prompt `List managed Docker stacks` to query plugin resources."


def dispatch_yaml(stack_name: str, _ctx: SlashDispatchContext) -> DirectSlashResult:
    return {"ok": True, "text": f"Use the agent prompt `Show YAML for stack {stack_name}`."}


def destroy_stack_prompt(stack_name: str, remove_volumes: bool = False) -> str:
    suffix = " with volumes" if remove_volumes else ""
    return f"Destroy stack {stack_name}{suffix}"


def stop_stack_prompt(stack_name: str, services: list[str] | None = None) -> str:
    if services:
        svc_list = ", ".join(services)
        return f"Stop stack {stack_name} services {svc_list}"
    return f"Stop stack {stack_name}"


def parse_direct_stop_stack(content: str) -> dict[str, str | list[str]] | None:
    trimmed = content.strip()
    patterns = [
        re.compile(r"^Stop stack (\S+)(?:\s+services?\s+(.+))?$", re.IGNORECASE),
        re.compile(r"^stop (\S+)(?:\s+services?\s+(.+))?$", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.match(trimmed)
        if not match or not match.group(1):
            continue
        stack_name = match.group(1)
        services_raw = match.group(2)
        if services_raw is None:
            return {"stack_name": stack_name}
        services = [part.strip() for part in re.split(r"[,\s]+", services_raw) if part.strip()]
        if not services:
            return {"stack_name": stack_name}
        return {"stack_name": stack_name, "services": services}
    return None


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


__all__ = [
    "DirectSlashResult",
    "SlashDispatchContext",
    "destroy_stack_prompt",
    "dispatch_stacks",
    "dispatch_yaml",
    "is_destroy_all_prompt",
    "parse_direct_destroy_stack",
    "parse_direct_stop_stack",
    "stop_stack_prompt",
]

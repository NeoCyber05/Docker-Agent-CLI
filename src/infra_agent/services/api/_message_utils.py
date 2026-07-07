"""Shared message serialization helpers for provider adapters."""

from __future__ import annotations

import json
from typing import Any

from infra_agent.types.message import Message


def message_role(message: Message) -> str:
    role = getattr(message, "role", None)
    if isinstance(role, str):
        return role
    if isinstance(message, dict):
        role_val = message.get("role")
        if isinstance(role_val, str):
            return role_val
    raise ValueError(f"Message missing role: {message!r}")


def block_type(block: Any) -> str | None:
    block_t = getattr(block, "type", None)
    if isinstance(block_t, str):
        return block_t
    if isinstance(block, dict):
        t = block.get("type")
        return t if isinstance(t, str) else None
    return None


def block_attr(block: Any, name: str, default: Any = None) -> Any:
    value = getattr(block, name, None)
    if value is not None:
        return value
    if isinstance(block, dict):
        return block.get(name, default)
    return default


def build_tool_use_to_name(messages: list[Message]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for message in messages:
        if message_role(message) != "assistant":
            continue
        content = getattr(message, "content", None) or []
        for block in content:
            if block_type(block) == "tool_use":
                mapping[block_attr(block, "id", "")] = block_attr(block, "name", "")
    return mapping


def build_openai_chat_messages(
    messages: list[Message],
    *,
    system: str,
) -> list[dict[str, Any]]:
    """Serialize messages to OpenAI chat completion format."""
    result: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        role = message_role(message)
        if role == "user":
            result.append({"role": "user", "content": getattr(message, "content", "")})
        elif role == "assistant":
            content = getattr(message, "content", None) or []
            text = "".join(
                block_attr(b, "text", "") for b in content if block_type(b) == "text"
            )
            tool_calls = [
                {
                    "id": block_attr(b, "id", ""),
                    "type": "function",
                    "function": {
                        "name": block_attr(b, "name", ""),
                        "arguments": json.dumps(block_attr(b, "input", {})),
                    },
                }
                for b in content
                if block_type(b) == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant"}
            msg["content"] = text if text else None
            if tool_calls:
                msg["tool_calls"] = tool_calls
            result.append(msg)
        elif role == "tool":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": getattr(message, "tool_use_id", None)
                    or block_attr(message, "toolUseId", ""),
                    "content": getattr(message, "content", ""),
                }
            )
    return result
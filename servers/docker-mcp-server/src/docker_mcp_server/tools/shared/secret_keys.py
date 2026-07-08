"""Collect known secret env keys for log scrubbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docker_mcp_server.state.env_file import read_env_file
from docker_mcp_server.state.secret_redactor import should_redact
from docker_mcp_server.state.state_store import StateStore


@dataclass
class SecretKeysContext:
    cwd: str
    state_store: StateStore


def _resolve_env_file(cwd: str, env_file_path: str) -> str:
    path = Path(env_file_path)
    if path.is_absolute():
        return str(path)
    return str(Path(cwd) / env_file_path)


def collect_secret_keys(stack_name: str, ctx: SecretKeysContext) -> set[str]:
    """Collect secret env keys for a stack from state and env files."""
    keys: set[str] = set()
    definition = ctx.state_store.read(stack_name)
    if definition is None:
        return keys

    for source in definition.x_infra_agent.env_file_sources.values():
        for key in source.added_keys or []:
            keys.add(key)

    for spec in definition.services.values():
        for key in spec.environment or {}:
            if should_redact(key):
                keys.add(key)
        for env_file in spec.env_file or []:
            values = read_env_file(_resolve_env_file(ctx.cwd, env_file))
            for key in values:
                if should_redact(key):
                    keys.add(key)

    return keys


__all__ = ["SecretKeysContext", "collect_secret_keys"]

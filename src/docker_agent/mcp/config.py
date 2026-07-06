"""MCP server configuration for feature-flagged plugin experiments."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class McpServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    args: list[str] = Field(default_factory=list)
    transport: Literal["stdio"] = "stdio"


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: dict[str, McpServerConfig]


DEFAULT_DOCKER_SERVER = McpServerConfig(
    command="docker-mcp-server",
    args=[],
    transport="stdio",
)


def is_mcp_enabled(env: os._Environ[str] | dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = source.get("DOCKER_AGENT_MCP")
    if raw is None or raw.strip() == "":
        return True
    value = raw.strip().lower()
    if value in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
        "legacy",
    }:
        raise RuntimeError(
            "DOCKER_AGENT_MCP=0 legacy MCP-off path has been removed. "
            "Run with MCP enabled and configure plugins through DOCKER_AGENT_MCP_CONFIG."
        )
    if value in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "mcp",
    }:
        return True
    raise RuntimeError(f"Unsupported DOCKER_AGENT_MCP value: {raw}")

def mcp_config_path() -> str:
    override = os.environ.get("DOCKER_AGENT_MCP_CONFIG")
    if override:
        return override
    return str(Path.home() / ".docker-agent" / "mcp_servers.json")


def default_mcp_config() -> McpConfig:
    return McpConfig(servers={"docker": DEFAULT_DOCKER_SERVER})


def load_mcp_config(path: str | os.PathLike[str] | None = None) -> McpConfig:
    target = Path(path) if path is not None else Path(mcp_config_path())
    if not target.exists():
        config = default_mcp_config()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(config.model_dump(), indent=2) + "\n",
            encoding="utf-8",
        )
        return config
    raw = json.loads(target.read_text(encoding="utf-8-sig"))
    return McpConfig.model_validate(raw)


def mcp_servers_for_langchain(config: McpConfig | None = None) -> dict[str, dict[str, object]]:
    effective = config or load_mcp_config()
    return {
        name: server.model_dump(exclude_none=True)
        for name, server in effective.servers.items()
    }


__all__ = [
    "DEFAULT_DOCKER_SERVER",
    "McpConfig",
    "McpServerConfig",
    "default_mcp_config",
    "is_mcp_enabled",
    "load_mcp_config",
    "mcp_config_path",
    "mcp_servers_for_langchain",
]



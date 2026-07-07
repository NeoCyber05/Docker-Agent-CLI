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
    # Presentation metadata for the plugin selector. Not sent to the MCP client.
    label: str | None = None
    description: str | None = None


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: dict[str, McpServerConfig]


class PluginDescriptor(BaseModel):
    """A connectable infrastructure plugin, as shown in the startup selector."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    description: str = ""


# Fields that describe the plugin to the user but must not be forwarded to the
# MCP transport client.
_PRESENTATION_FIELDS = {"label", "description"}


DEFAULT_DOCKER_SERVER = McpServerConfig(
    command="docker-mcp-server",
    args=[],
    transport="stdio",
    label="Docker",
    description="Deploy and manage Docker Compose stacks",
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


def mcp_servers_for_langchain(
    config: McpConfig | None = None,
    *,
    selected: list[str] | None = None,
) -> dict[str, dict[str, object]]:
    """Build the MCP client server map.

    ``selected`` restricts the returned servers to the chosen plugin names. When it
    is ``None`` every configured server is returned, so callers that do not care
    about session-level plugin selection (and tests) get the full set.
    """
    effective = config or load_mcp_config()
    selected_set = set(selected) if selected is not None else None
    return {
        name: server.model_dump(exclude_none=True, exclude=_PRESENTATION_FIELDS)
        for name, server in effective.servers.items()
        if selected_set is None or name in selected_set
    }


def list_available_plugins(config: McpConfig | None = None) -> list[PluginDescriptor]:
    """List connectable plugins from the MCP config, for the startup selector."""
    effective = config or load_mcp_config()
    return [
        PluginDescriptor(
            name=name,
            label=server.label or name,
            description=server.description or "",
        )
        for name, server in effective.servers.items()
    ]


def plugin_selection_path() -> str:
    override = os.environ.get("DOCKER_AGENT_PLUGIN_SELECTION")
    if override:
        return override
    return str(Path.home() / ".docker-agent" / "plugin-selection.json")


def load_plugin_selection(path: str | os.PathLike[str] | None = None) -> list[str] | None:
    """Return the previously selected plugin names, or ``None`` if never chosen."""
    target = Path(path) if path is not None else Path(plugin_selection_path())
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    selected = raw.get("selected") if isinstance(raw, dict) else None
    if not isinstance(selected, list):
        return None
    return [str(item) for item in selected]


def save_plugin_selection(
    names: list[str],
    path: str | os.PathLike[str] | None = None,
) -> None:
    target = Path(path) if path is not None else Path(plugin_selection_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"selected": list(names)}, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "DEFAULT_DOCKER_SERVER",
    "McpConfig",
    "McpServerConfig",
    "PluginDescriptor",
    "default_mcp_config",
    "is_mcp_enabled",
    "list_available_plugins",
    "load_mcp_config",
    "load_plugin_selection",
    "mcp_config_path",
    "mcp_servers_for_langchain",
    "plugin_selection_path",
    "save_plugin_selection",
]



from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra_agent.mcp.config import (
    DEFAULT_DOCKER_SERVER,
    is_mcp_enabled,
    load_mcp_config,
    mcp_config_path,
)


def test_mcp_flag_accepts_explicit_truthy_values(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_MCP", "1")
    assert is_mcp_enabled()

    monkeypatch.setenv("DOCKER_AGENT_MCP", "true")
    assert is_mcp_enabled()


def test_mcp_flag_defaults_to_enabled(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_MCP", raising=False)
    assert is_mcp_enabled()


def test_mcp_config_path_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "mcp_servers.json"
    monkeypatch.setenv("DOCKER_AGENT_MCP_CONFIG", str(path))
    assert mcp_config_path() == str(path)


def test_load_mcp_config_creates_default_docker_entry(tmp_path: Path) -> None:
    path = tmp_path / "mcp_servers.json"

    config = load_mcp_config(path)

    assert config.servers["docker"] == DEFAULT_DOCKER_SERVER
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "servers": {
            "docker": {
                "command": "docker-mcp-server",
                "args": [],
                "transport": "stdio",
                "label": "Docker",
                "description": "Deploy and manage Docker Compose stacks",
            }
        }
    }


def test_load_mcp_config_reads_existing_entries(tmp_path: Path) -> None:
    path = tmp_path / "mcp_servers.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "docker": {
                        "command": "custom-docker-server",
                        "args": ["--stdio"],
                        "transport": "stdio",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(path)

    assert config.servers["docker"].command == "custom-docker-server"
    assert config.servers["docker"].args == ["--stdio"]


def test_load_mcp_config_accepts_utf8_bom_from_windows_tools(tmp_path: Path) -> None:
    path = tmp_path / "mcp_servers.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "docker": {
                        "command": "custom-docker-server",
                        "args": [],
                        "transport": "stdio",
                    }
                }
            }
        ),
        encoding="utf-8-sig",
    )

    config = load_mcp_config(path)

    assert config.servers["docker"].command == "custom-docker-server"


def test_mcp_defaults_to_enabled(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_AGENT_MCP", raising=False)
    assert is_mcp_enabled()


def test_mcp_flag_rejects_legacy_false_values(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_MCP", "0")
    with pytest.raises(RuntimeError, match="legacy MCP-off path has been removed"):
        is_mcp_enabled()

    monkeypatch.setenv("DOCKER_AGENT_MCP", "false")
    with pytest.raises(RuntimeError, match="legacy MCP-off path has been removed"):
        is_mcp_enabled()




def test_list_available_plugins_exposes_label_and_description(tmp_path: Path) -> None:
    from infra_agent.mcp.config import list_available_plugins

    config = load_mcp_config(tmp_path / "mcp_servers.json")

    plugins = list_available_plugins(config)

    assert [p.name for p in plugins] == ["docker"]
    assert plugins[0].label == "Docker"
    assert "Docker Compose" in plugins[0].description


def test_servers_for_langchain_strips_presentation_fields(tmp_path: Path) -> None:
    from infra_agent.mcp.config import mcp_servers_for_langchain

    config = load_mcp_config(tmp_path / "mcp_servers.json")

    servers = mcp_servers_for_langchain(config)

    assert servers["docker"] == {
        "command": "docker-mcp-server",
        "args": [],
        "transport": "stdio",
    }


def test_servers_for_langchain_filters_by_selection() -> None:
    from infra_agent.mcp.config import McpConfig, McpServerConfig, mcp_servers_for_langchain

    config = McpConfig(
        servers={
            "docker": McpServerConfig(command="docker-mcp-server"),
            "k8s": McpServerConfig(command="k8s-mcp-server"),
        }
    )

    assert set(mcp_servers_for_langchain(config)) == {"docker", "k8s"}
    assert set(mcp_servers_for_langchain(config, selected=["k8s"])) == {"k8s"}
    assert mcp_servers_for_langchain(config, selected=[]) == {}


def test_plugin_selection_round_trip(tmp_path: Path) -> None:
    from infra_agent.mcp.config import load_plugin_selection, save_plugin_selection

    path = tmp_path / "plugin-selection.json"

    assert load_plugin_selection(path) is None

    save_plugin_selection(["docker", "k8s"], path)

    assert load_plugin_selection(path) == ["docker", "k8s"]


def test_plugin_selection_ignores_corrupt_file(tmp_path: Path) -> None:
    from infra_agent.mcp.config import load_plugin_selection

    path = tmp_path / "plugin-selection.json"
    path.write_text("not json", encoding="utf-8")

    assert load_plugin_selection(path) is None

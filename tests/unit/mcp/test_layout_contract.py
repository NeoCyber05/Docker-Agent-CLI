from __future__ import annotations

import importlib
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_mcp_client_modules_live_outside_engine() -> None:
    for module_name in (
        "docker_agent.mcp.config",
        "docker_agent.mcp.commands",
        "docker_agent.mcp.client",
        "docker_agent.mcp.capabilities",
        "docker_agent.mcp.approval",
    ):
        importlib.import_module(module_name)


def test_legacy_mcp_modules_are_removed() -> None:
    for module_name in (
        "docker_agent.mcp_config",
        "docker_agent.command_router",
        "docker_agent.engine.mcp_tools",
        "docker_agent.engine.confirmation",
    ):
        assert importlib.util.find_spec(module_name) is None


def test_docker_mcp_server_workspace_name_and_command(tmp_path: Path, monkeypatch) -> None:
    server_dir = ROOT / "servers" / "docker-mcp-server"
    assert server_dir.exists()
    assert not (ROOT / "servers" / "docker-agent-mcp").exists()

    root_pyproject = _load_toml(ROOT / "pyproject.toml")
    assert "servers/docker-mcp-server" in root_pyproject["tool"]["uv"]["workspace"]["members"]
    assert "docker-mcp-server" in root_pyproject["project"]["optional-dependencies"]["docker"]
    assert root_pyproject["tool"]["uv"]["sources"]["docker-mcp-server"] == {
        "workspace": True
    }
    assert "servers/docker-mcp-server/src" in root_pyproject["tool"]["pytest"]["ini_options"][
        "pythonpath"
    ]

    server_pyproject = _load_toml(server_dir / "pyproject.toml")
    assert server_pyproject["project"]["name"] == "docker-mcp-server"
    assert server_pyproject["project"]["scripts"] == {
        "docker-mcp-server": "docker_mcp_server.server:main"
    }

    monkeypatch.setenv("DOCKER_AGENT_MCP_CONFIG", str(tmp_path / "mcp_servers.json"))
    config = importlib.import_module("docker_agent.mcp.config")
    servers = config.mcp_servers_for_langchain()
    assert servers["docker"]["command"] == "docker-mcp-server"


def test_no_generated_egg_info_in_source_tree() -> None:
    generated = [
        path
        for path in ROOT.rglob("*.egg-info")
        if "site-packages" not in path.parts and ".venv" not in path.parts
    ]
    assert generated == []
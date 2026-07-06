from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _matches(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return module_name in prefixes or module_name.startswith(
        tuple(f"{prefix}." for prefix in prefixes)
    )


def test_docker_mcp_server_imports_no_core_package_modules() -> None:
    server_src = ROOT / "servers" / "docker-mcp-server" / "src" / "docker_mcp_server"
    offenders: list[str] = []
    for path in sorted(server_src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for module_name in _import_modules(path):
            if _matches(module_name, ("docker_agent",)):
                offenders.append(f"{path.relative_to(ROOT)} imports {module_name}")

    assert offenders == []


def test_core_has_no_docker_plugin_or_legacy_imports() -> None:
    core_src = ROOT / "src" / "docker_agent"
    forbidden_prefixes = (
        "docker_mcp_server",
        "docker_agent.tools",
        "docker_mcp_server.services.docker",
        "docker_agent.policy",
        "docker_mcp_server.types.stack",
    )
    offenders: list[str] = []
    for path in sorted(core_src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for module_name in _import_modules(path):
            if _matches(module_name, forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT)} imports {module_name}")

    assert offenders == []


def test_langgraph_backend_import_does_not_load_legacy_docker_modules() -> None:
    code = """
import importlib
import json
import sys

importlib.import_module("docker_agent.engine.langgraph.backend")

loaded = sorted(
    name
    for name in sys.modules
    if (
        name == "docker_agent.tools"
        or name.startswith("docker_mcp_server.tools.")
        or name == "docker_mcp_server.services.docker"
        or name.startswith("docker_mcp_server.services.docker.")
        or name == "docker_mcp_server"
        or name.startswith("docker_mcp_server.")
    )
)
print(json.dumps(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert json.loads(result.stdout) == []


def test_legacy_docker_shims_are_removed_from_core_package() -> None:
    removed_paths = [
        ROOT / "src" / "docker_agent" / "tools",
        ROOT / "src" / "docker_agent" / "services" / "docker",
        ROOT / "src" / "docker_agent" / "compat" / "docker_apply.py",
        ROOT / "src" / "docker_agent" / "query.py",
    ]
    assert [str(path.relative_to(ROOT)) for path in removed_paths if path.exists()] == []


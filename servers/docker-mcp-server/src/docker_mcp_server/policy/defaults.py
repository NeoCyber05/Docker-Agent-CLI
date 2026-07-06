"""Default global policy scaffolding.

Baseline matches the global example in ``docs/policies.md``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from pathlib import Path

import yaml

from docker_mcp_server.policy.types import PolicyConfig

DEFAULT_GLOBAL_POLICY_YAML = """\
schemaVersion: "1"

global:
  hardDeny:
    - privileged_containers
    - mount_docker_socket
    - mount_host_root
    - host_pid_namespace
    - host_network
    - add_all_linux_capabilities
    - disable_seccomp
    - untrusted_registry:
        allowedRegistries:
          - docker.io
          - gcr.io
    - expose_database_publicly
  require:
    - restart_policy
    - resource_limits:
        memoryRequired: true
        maxMemory: 8GiB
    - logging_rotation:
        maxSize: 50m
        maxFiles: 5
"""


def global_policy_path() -> str:
    """Return the default global policy file path."""
    override = os.environ.get("DOCKER_AGENT_GLOBAL_POLICY")
    if override:
        return override
    return str(Path.home() / ".docker-agent" / "policies.yaml")


def ensure_global_policy(path: str | os.PathLike[str] | None = None) -> bool:
    """Create the baseline global policy file when missing.

    Returns ``True`` if a new file was written, ``False`` if it already existed.
    """
    target = Path(path) if path is not None else Path(global_policy_path())
    if target.exists():
        return False

    PolicyConfig.model_validate(yaml.safe_load(DEFAULT_GLOBAL_POLICY_YAML))

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{target}.tmp")
    try:
        tmp_path.write_text(DEFAULT_GLOBAL_POLICY_YAML, encoding="utf-8")
        shutil.move(str(tmp_path), str(target))
    except Exception as err:  # noqa: BLE001
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        print(
            f"[docker-agent] Failed to initialize global policy at {target}: {err}",
            file=sys.stderr,
        )
        return False

    print(
        f"[docker-agent] Initialized default global policy at {target}",
        file=sys.stderr,
    )
    return True


__all__ = ["DEFAULT_GLOBAL_POLICY_YAML", "ensure_global_policy", "global_policy_path"]


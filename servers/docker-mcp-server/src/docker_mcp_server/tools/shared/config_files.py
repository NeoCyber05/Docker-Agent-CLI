"""Config file bind-mount staging and rollback helpers.

Parity: ``src/tools/shared/configFiles.ts``.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docker_mcp_server.types.stack import ServiceSpec

RESERVED_DIR = ".docker-agent"
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 256 * 1024


@dataclass
class BindMount:
    source: str
    target: str
    mode: str | None = None


@dataclass
class StagedConfigFile:
    path: str
    content: str
    bytes: int


@dataclass
class ConfigFileSnapshot:
    abs: str
    existed: bool
    previous_content: str | None


def normalize_rel(path: str) -> str:
    """Normalize a host-relative path to forward slashes with no leading './'."""
    norm = Path(path).as_posix()
    return re.sub(r"^\./", "", norm)


def parse_bind_mount(volume: str) -> BindMount | None:
    """Parse short-syntax volume ``SOURCE:TARGET[:MODE]``."""
    parts = volume.split(":")
    if len(parts) < 2:
        return None
    source = parts[0]
    target = parts[1]
    mode = parts[2] if len(parts) > 2 else None
    if not re.match(r"^[.~/]", source):
        return None
    return BindMount(source=source, target=target, mode=mode)


def is_file_like_bind(source: str) -> bool:
    """True when the host path basename carries an extension."""
    return bool(re.search(r"\.[A-Za-z0-9]+$", Path(source).name))


def resolve_safe(
    cwd: str | os.PathLike[str], rel_path: str
) -> dict[str, str] | dict[str, object]:
    """Confine a host-relative path to cwd."""
    if Path(rel_path).is_absolute():
        return {"ok": False, "error": "absolute paths are not allowed"}
    abs_path = Path(cwd).resolve() / rel_path
    abs_path = abs_path.resolve()
    cwd_resolved = Path(cwd).resolve()
    try:
        rel = abs_path.relative_to(cwd_resolved)
    except ValueError:
        return {"ok": False, "error": "path escapes the project directory"}
    first = normalize_rel(str(rel)).split("/")[0]
    if first == RESERVED_DIR:
        return {"ok": False, "error": f"{RESERVED_DIR} is reserved"}
    return {"ok": True, "abs": str(abs_path)}


def detect_missing_config_files(
    services: dict[str, ServiceSpec],
    provided_keys: set[str],
    cwd: str | os.PathLike[str],
) -> list[dict[str, str]]:
    """File-like bind mounts missing content and host file."""
    missing: list[dict[str, str]] = []
    for service, spec in services.items():
        for vol in spec.volumes or []:
            bind = parse_bind_mount(vol)
            if bind is None or not is_file_like_bind(bind.source):
                continue
            if normalize_rel(bind.source) in provided_keys:
                continue
            safe = resolve_safe(cwd, bind.source)
            if not safe.get("ok"):
                continue
            abs_path = str(safe["abs"])
            if not Path(abs_path).exists():
                missing.append({"service": service, "path": bind.source})
    return missing


def find_invalid_file_binds(
    services: dict[str, ServiceSpec],
    cwd: str | os.PathLike[str],
) -> list[dict[str, str]]:
    """Detect missing or directory-squatting file bind sources."""
    bad: list[dict[str, str]] = []
    for service, spec in services.items():
        for vol in spec.volumes or []:
            bind = parse_bind_mount(vol)
            if bind is None or not is_file_like_bind(bind.source):
                continue
            safe = resolve_safe(cwd, bind.source)
            if not safe.get("ok"):
                continue
            abs_path = Path(str(safe["abs"]))
            if not abs_path.exists():
                bad.append(
                    {"service": service, "path": bind.source, "reason": "missing"}
                )
            elif abs_path.is_dir():
                bad.append(
                    {"service": service, "path": bind.source, "reason": "directory"}
                )
    return bad


def stage_config_files(
    cwd: str | os.PathLike[str],
    services: dict[str, ServiceSpec],
    config_files: dict[str, str] | None,
) -> dict[str, object]:
    """Validate provided configFiles against file binds and size caps."""
    provided = config_files or {}
    file_binds: set[str] = set()
    for spec in services.values():
        for vol in spec.volumes or []:
            bind = parse_bind_mount(vol)
            if bind is not None and is_file_like_bind(bind.source):
                file_binds.add(normalize_rel(bind.source))

    total = 0
    staged: list[StagedConfigFile] = []
    for key, content in provided.items():
        safe = resolve_safe(cwd, key)
        if not safe.get("ok"):
            return {
                "ok": False,
                "error": f'unsafe config file path "{key}": {safe["error"]}',
            }
        norm = normalize_rel(key)
        if norm not in file_binds:
            return {
                "ok": False,
                "error": f'configFiles entry "{key}" matches no file bind mount',
            }
        nbytes = len(content.encode("utf-8"))
        if nbytes > MAX_FILE_BYTES:
            return {
                "ok": False,
                "error": f'config file "{key}" exceeds 64 KiB',
            }
        total += nbytes
        staged.append(StagedConfigFile(path=norm, content=content, bytes=nbytes))

    if total > MAX_TOTAL_BYTES:
        return {"ok": False, "error": "config files total exceeds 256 KiB"}
    return {"ok": True, "staged": staged}


def snapshot_config_files(
    cwd: str | os.PathLike[str], files: list[StagedConfigFile]
) -> list[ConfigFileSnapshot]:
    """Snapshot existing file content before staging writes."""
    snapshots: list[ConfigFileSnapshot] = []
    for file in files:
        abs_path = Path(cwd).resolve() / file.path
        existed = abs_path.is_file()
        previous = abs_path.read_text(encoding="utf-8") if existed else None
        snapshots.append(
            ConfigFileSnapshot(
                abs=str(abs_path),
                existed=existed,
                previous_content=previous,
            )
        )
    return snapshots


def write_config_files(
    cwd: str | os.PathLike[str], files: list[StagedConfigFile]
) -> None:
    """Write staged config files, recovering from directory squatters."""
    for file in files:
        safe = resolve_safe(cwd, file.path)
        if not safe.get("ok"):
            raise ValueError(f'refusing to write "{file.path}": {safe["error"]}')
        abs_path = Path(str(safe["abs"]))
        if abs_path.exists() and abs_path.is_dir():
            shutil.rmtree(abs_path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(file.content, encoding="utf-8")


def restore_config_files(snapshots: list[ConfigFileSnapshot]) -> None:
    """Restore config files from snapshots after a failed apply."""
    for snapshot in snapshots:
        path = Path(snapshot.abs)
        if snapshot.existed:
            path.write_text(snapshot.previous_content or "", encoding="utf-8")
        elif path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


__all__ = [
    "BindMount",
    "ConfigFileSnapshot",
    "StagedConfigFile",
    "detect_missing_config_files",
    "find_invalid_file_binds",
    "is_file_like_bind",
    "normalize_rel",
    "parse_bind_mount",
    "resolve_safe",
    "restore_config_files",
    "snapshot_config_files",
    "stage_config_files",
    "write_config_files",
]

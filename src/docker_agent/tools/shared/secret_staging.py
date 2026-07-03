"""Secret .env staging helpers — defer disk writes until apply stage."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from docker_agent.state.env_file import read_env_file, render_env_file


@dataclass
class StagedSecretFile:
    path: str
    values: dict[str, str]


@dataclass
class SecretFileSnapshot:
    path: str
    existed: bool
    previous_content: str | None


class SecretFileStager:
    """Accumulate .env writes in memory; no disk I/O until apply."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, str]] = {}

    def read(self, path: Path) -> dict[str, str]:
        disk = read_env_file(path)
        pending = self._pending.get(str(path))
        return {**disk, **pending} if pending else disk

    def stage(self, path: Path, values: dict[str, str]) -> None:
        self._pending[str(path)] = {**self.read(path), **values}

    def staged_files(self) -> list[StagedSecretFile]:
        return [StagedSecretFile(path=p, values=v) for p, v in self._pending.items()]


def snapshot_secret_files(files: list[StagedSecretFile]) -> list[SecretFileSnapshot]:
    snapshots: list[SecretFileSnapshot] = []
    for file in files:
        path = Path(file.path)
        existed = path.is_file()
        previous = path.read_text(encoding="utf-8") if existed else None
        snapshots.append(
            SecretFileSnapshot(path=str(path), existed=existed, previous_content=previous)
        )
    return snapshots


def write_secret_files(files: list[StagedSecretFile]) -> None:
    for file in files:
        path = Path(file.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_env_file(file.values), encoding="utf-8")
        os.chmod(path, 0o600)


def restore_secret_files(snapshots: list[SecretFileSnapshot]) -> None:
    for snapshot in snapshots:
        path = Path(snapshot.path)
        if snapshot.existed:
            path.write_text(snapshot.previous_content or "", encoding="utf-8")
            os.chmod(path, 0o600)
        elif path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


__all__ = [
    "SecretFileSnapshot",
    "SecretFileStager",
    "StagedSecretFile",
    "restore_secret_files",
    "snapshot_secret_files",
    "write_secret_files",
]

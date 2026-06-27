"""YAML stack state store with archive, history, and file locking.

Parity: ``src/state/StateStore.ts:1-319``.
"""

import contextlib
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docker_agent.config import STACK_STATES_DIR_NAME
from docker_agent.state.secret_redactor import should_redact
from docker_agent.types.stack import StackDefinition, StackSummary

HistoryAction = Literal[
    "plan", "apply", "destroy", "drift_detected", "rollback", "remediate"
]


class HistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    ts: str
    session_id: str = Field(alias="sessionId")
    stack_name: str = Field(alias="stackName")
    action: HistoryAction
    details: dict[str, Any]


WarnFn = Callable[[str], None]


def _default_warn(message: str) -> None:
    print(f"[docker-agent] {message}", file=sys.stderr)


def _error_message(err: object) -> str:
    if isinstance(err, Exception):
        return str(err)
    return str(err)


def _format_zod_issues(err: object) -> str:
    if isinstance(err, ValidationError):
        parts = []
        for e in err.errors():
            loc = "/".join(str(x) for x in e["loc"]) or "<root>"
            parts.append(f"{loc}: {e['msg']}")
        return "; ".join(parts)
    return _error_message(err)


def _parse_stack_definition(raw: object, source: str) -> StackDefinition:
    try:
        return StackDefinition.model_validate(raw)
    except Exception as err:
        raise ValueError(
            f"Invalid stack state at {source}: {_format_zod_issues(err)}"
        ) from err


class StateStore:
    """Owns ``docker-stacks/<name>.yaml`` plus archive/history/locks."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        states_dir: str | os.PathLike[str] | None = None,
        warn: WarnFn | None = None,
    ) -> None:
        self._root = Path(root)
        self.warn = warn if warn is not None else _default_warn

        if states_dir is not None:
            self._states_dir = Path(states_dir)
        elif self._root.name == ".docker-agent":
            self._states_dir = self._root.parent / STACK_STATES_DIR_NAME
        else:
            self._states_dir = self._root / STACK_STATES_DIR_NAME

        self._archive_dir = self._root / "archive"
        self._locks_dir = self._root / "locks"

        self._migrate_legacy_stacks_dir()
        self._states_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        (self._root / "sessions").mkdir(parents=True, exist_ok=True)
        self._locks_dir.mkdir(parents=True, exist_ok=True)
        (self._root / "logs").mkdir(parents=True, exist_ok=True)
        (self._root / "secrets").mkdir(parents=True, exist_ok=True, mode=0o700)

    def _migrate_legacy_stacks_dir(self) -> None:
        legacy = self._root / "stacks"
        if legacy.exists() and not self._states_dir.exists():
            shutil.move(str(legacy), str(self._states_dir))

    def _stack_path(self, name: str) -> Path:
        return self._states_dir / f"{name}.yaml"

    def read(self, name: str) -> StackDefinition | None:
        p = self._stack_path(name)
        if not p.exists():
            return None
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return _parse_stack_definition(raw, str(p))

    def write(self, name: str, definition: StackDefinition) -> None:
        target = self._stack_path(name)
        tmp = Path(f"{target}.tmp")
        tmp.write_text(
            yaml.safe_dump(definition.model_dump(by_alias=True), sort_keys=False),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o644)
        shutil.move(str(tmp), str(target))

    def list(self) -> list[StackSummary]:
        out: list[StackSummary] = []
        if not self._states_dir.exists():
            return out
        for entry in self._states_dir.iterdir():
            if not entry.is_file() or not entry.name.endswith(".yaml"):
                continue
            try:
                raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
                definition = _parse_stack_definition(raw, str(entry))
            except Exception as err:  # noqa: BLE001
                self.warn(
                    f"Skipping invalid stack state at {entry}: {_error_message(err)}"
                )
                continue
            meta = definition.x_docker_agent
            out.append(
                StackSummary.model_validate(
                    {
                        "name": meta.name,
                        "service_count": len(definition.services),
                        "last_applied": meta.last_applied,
                    }
                )
            )
        return out

    def remove(self, name: str, *, archive: bool = True) -> None:
        src = self._stack_path(name)
        if not src.exists():
            return
        if archive:
            ts = re.sub(
                r"[:.]",
                "-",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            )
            dst = self._archive_dir / f"{name}-{ts}.yaml"
            shutil.move(str(src), str(dst))
            shutil.copy2(str(dst), str(self._archive_dir / f"{name}.yaml"))
        else:
            src.unlink()

    def read_archive(self, name: str) -> StackDefinition | None:
        p = self._archive_dir / f"{name}.yaml"
        if not p.exists():
            return None
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            return _parse_stack_definition(raw, str(p))
        except Exception as err:  # noqa: BLE001
            self.warn(f"readArchive: could not parse archive for {name}: {_error_message(err)}")
            return None

    def has_archive_marker(self, name: str) -> bool:
        try:
            for entry in self._archive_dir.iterdir():
                if entry.name.startswith(name) and entry.name.endswith(".yaml"):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def append_history(self, event: HistoryEvent) -> None:
        p = self._root / "history.json"
        line = json.dumps(event.model_dump(by_alias=True)) + "\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(line)

    def acquire_lock(
        self, name: str, *, timeout_ms: int = 0
    ) -> Callable[[], None]:
        lock_path = self._locks_dir / f"{name}.lock"
        deadline = time.monotonic() * 1000 + timeout_ms

        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(str(os.getpid()))
                break
            except FileExistsError:
                if self._remove_stale_lock(lock_path):
                    continue
                if time.monotonic() * 1000 >= deadline:
                    raise RuntimeError(f"acquireLock: lock held for {name}") from None
                time.sleep(0.01)

        def unlock() -> None:
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()

        return unlock

    def _remove_stale_lock(self, lock_path: Path) -> bool:
        try:
            text = lock_path.read_text(encoding="utf-8").strip()
            pid = int(text)
            if pid > 0 and self._is_process_alive(pid):
                return False
            lock_path.unlink()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _is_process_alive(self, pid: int) -> bool:
        if sys.platform == "win32":
            import ctypes

            process_query_limited = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(process_query_limited, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:  # noqa: BLE001
            return True

    def summary(self) -> str:
        out: dict[str, dict[str, Any]] = {}
        for summary in self.list():
            definition = self.read(summary.name)
            if definition is None:
                continue
            meta = definition.x_docker_agent
            services_out: dict[str, dict[str, Any]] = {}
            for svc_name, spec in definition.services.items():
                visible_env: dict[str, str] = {}
                for k, v in (spec.environment or {}).items():
                    visible_env[k] = "***" if should_redact(k) else v
                services_out[svc_name] = {
                    "image": spec.image,
                    "ports": spec.ports or [],
                    "scale": spec.scale if spec.scale is not None else 1,
                    "environment": visible_env,
                    "env_file": spec.env_file or [],
                }
            out[summary.name] = {
                "lastApplied": meta.last_applied,
                "services": services_out,
            }
        return str(yaml.safe_dump(out, sort_keys=False))


__all__ = [
    "HistoryAction",
    "HistoryEvent",
    "StateStore",
]
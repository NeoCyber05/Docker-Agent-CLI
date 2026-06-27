"""Git status guard for env files.

Parity: ``src/services/docker/gitGuard.ts``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class GitRunner(Protocol):
    def exists(self, cwd: str) -> bool: ...

    async def run(self, args: list[str], cwd: str) -> int: ...


class RealGitRunner:
    def exists(self, cwd: str) -> bool:
        return Path(cwd, ".git").exists()

    async def run(self, args: list[str], cwd: str) -> int:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode or 0


@dataclass(frozen=True)
class GitStatusReport:
    refusals: list[str]
    warnings: list[str]
    skipped: bool


async def check_env_file_git_status(
    env_files: list[str],
    cwd: str,
    *,
    git: GitRunner | None = None,
) -> GitStatusReport:
    """Check whether env files are tracked, ignored, or untracked by git."""
    runner = git if git is not None else RealGitRunner()
    if not runner.exists(cwd):
        return GitStatusReport(refusals=[], warnings=[], skipped=True)

    refusals: list[str] = []
    warnings: list[str] = []
    for f in env_files:
        tracked = await runner.run(["ls-files", "--error-unmatch", "--", f], cwd)
        if tracked == 0:
            refusals.append(f)
            continue
        ignored = await runner.run(["check-ignore", "-q", "--", f], cwd)
        if ignored != 0:
            warnings.append(f)
    return GitStatusReport(refusals=refusals, warnings=warnings, skipped=False)


__all__ = [
    "GitRunner",
    "GitStatusReport",
    "RealGitRunner",
    "check_env_file_git_status",
]
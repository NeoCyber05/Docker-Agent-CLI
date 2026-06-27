"""Parity tests for git_guard — mirrors src/services/docker/gitGuard.ts."""

import pytest

from docker_agent.services.docker.git_guard import (
    GitRunner,
    check_env_file_git_status,
)


class FakeGitRunner(GitRunner):
    def __init__(
        self, exists: bool = True, codes: dict[tuple[str, ...], int] | None = None
    ) -> None:
        self._exists = exists
        self.codes = codes or {}
        self.calls: list[tuple[list[str], str]] = []

    def exists(self, cwd: str) -> bool:
        return self._exists

    async def run(self, args: list[str], cwd: str) -> int:
        self.calls.append((args, cwd))
        return self.codes.get(tuple(args), 1)


@pytest.mark.asyncio
async def test_no_git_dir_skips() -> None:
    git = FakeGitRunner(exists=False)
    report = await check_env_file_git_status([".env"], "/tmp", git=git)
    assert report.skipped is True
    assert report.refusals == []
    assert report.warnings == []


@pytest.mark.asyncio
async def test_tracked_file_is_refusal() -> None:
    git = FakeGitRunner(codes={("ls-files", "--error-unmatch", "--", ".env"): 0})
    report = await check_env_file_git_status([".env"], "/tmp", git=git)
    assert ".env" in report.refusals
    assert ".env" not in report.warnings


@pytest.mark.asyncio
async def test_ignored_file_is_ok() -> None:
    git = FakeGitRunner(
        codes={
            ("ls-files", "--error-unmatch", "--", ".env"): 1,
            ("check-ignore", "-q", "--", ".env"): 0,
        }
    )
    report = await check_env_file_git_status([".env"], "/tmp", git=git)
    assert ".env" not in report.refusals
    assert ".env" not in report.warnings


@pytest.mark.asyncio
async def test_untracked_unignored_is_warning() -> None:
    git = FakeGitRunner(
        codes={
            ("ls-files", "--error-unmatch", "--", ".env"): 1,
            ("check-ignore", "-q", "--", ".env"): 1,
        }
    )
    report = await check_env_file_git_status([".env"], "/tmp", git=git)
    assert ".env" not in report.refusals
    assert ".env" in report.warnings
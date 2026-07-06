"""Parity tests for compose_runner â€” mirrors src/services/docker/composeRunner.ts."""

import sys
from collections.abc import AsyncIterator

import pytest

from docker_mcp_server.services.docker.compose_runner import (
    BoundComposeRunner,
    _default_spawner_impl,
)


class FakeSpawner:
    def __init__(self, lines: list[str], exit_code: int = 0) -> None:
        self.lines = lines
        self.exit_code = exit_code
        self.calls: list[tuple[str, list[str], dict]] = []

    def spawn(
        self, cmd: str, args: list[str], opts: dict
    ) -> AsyncIterator[str]:
        return self._spawn(cmd, args, opts)

    async def _spawn(
        self, cmd: str, args: list[str], opts: dict
    ) -> AsyncIterator[str]:
        self.calls.append((cmd, args, opts))
        for line in self.lines:
            yield line


@pytest.mark.asyncio
async def test_bound_runner_base_args() -> None:
    fake = FakeSpawner([])
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    args = runner.base_args()
    assert args == [
        "compose",
        "-p",
        "web",
        "--project-directory",
        "/tmp",
        "-f",
        "/tmp/web.yaml",
    ]


@pytest.mark.asyncio
async def test_up_detach_and_scale() -> None:
    fake = FakeSpawner(["done"], exit_code=0)
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    lines = []
    async for line in runner.up(detach=True, scale={"web": 2}):
        lines.append(line)
    assert fake.calls[0][1] == [
        "compose",
        "-p",
        "web",
        "--project-directory",
        "/tmp",
        "-f",
        "/tmp/web.yaml",
        "up",
        "-d",
        "--scale",
        "web=2",
    ]


@pytest.mark.asyncio
async def test_down_with_volumes() -> None:
    fake = FakeSpawner([])
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    async for _ in runner.down(volumes=True):
        pass
    assert "-v" in fake.calls[0][1]


@pytest.mark.asyncio
async def test_stop_all_services() -> None:
    fake = FakeSpawner([" Container web-1  Stopped"])
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    async for _ in runner.stop():
        pass
    args = fake.calls[0][1]
    assert "stop" in args
    assert args[-1] != "wordpress"


@pytest.mark.asyncio
async def test_stop_specific_services() -> None:
    fake = FakeSpawner([])
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    async for _ in runner.stop(services=["wordpress", "mysql"]):
        pass
    args = fake.calls[0][1]
    assert args[-2:] == ["wordpress", "mysql"]


@pytest.mark.asyncio
async def test_ps_parses_json_lines() -> None:
    fake = FakeSpawner(
        [
            '{"Name": "web-1", "Service": "web", "State": "running", "Health": "healthy"}',
            "not-json",
            '{"Name": "web-2", "Service": "web", "State": "exited"}',
            '{"Name": "web-3", "Service": "wordpress", "State": "running", "Health": ""}',
        ]
    )
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    rows = await runner.ps(json=True)
    assert len(rows) == 3
    assert rows[0].name == "web-1"
    assert rows[1].health is None
    assert rows[2].health is None


@pytest.mark.asyncio
async def test_logs_args() -> None:
    fake = FakeSpawner(["log line"])
    runner = BoundComposeRunner("web", "/tmp/web.yaml", "/tmp", fake)
    async for _line in runner.logs(service="web", tail_lines=10, follow=True):
        pass
    args = fake.calls[0][1]
    assert "logs" in args
    assert "-f" in args
    assert "--tail" in args
    assert "10" in args
    assert "web" in args


@pytest.mark.asyncio
async def test_default_spawner_streams_before_process_exit() -> None:
    script = (
        "import time; print('first-line', flush=True); "
        "time.sleep(0.2); print('second-line', flush=True)"
    )
    lines: list[str] = []
    try:
        async for line in _default_spawner_impl(
            sys.executable,
            ["-c", script],
            {"cwd": "."},
        ):
            lines.append(line)
    except PermissionError as err:
        if sys.platform == "win32":
            pytest.skip(f"Windows sandbox blocked subprocess pipes: {err}")
        raise
    assert lines[:2] == ["first-line", "second-line"]




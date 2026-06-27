"""Subprocess runner for ``docker compose`` commands.

Parity: ``src/services/docker/composeRunner.ts:1-178``.
"""

from __future__ import annotations

import asyncio
import json as json_module
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


class Spawner(Protocol):
    def spawn(
        self, cmd: str, args: list[str], opts: dict[str, Any]
    ) -> AsyncIterator[str]: ...


async def _default_spawner_impl(
    cmd: str, args: list[str], opts: dict[str, Any]
) -> AsyncIterator[str]:
    """Default subprocess spawner using ``asyncio.create_subprocess_exec``."""
    cwd = opts["cwd"]
    signal = opts.get("signal")

    proc = await asyncio.create_subprocess_exec(
        cmd,
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    abort_task: asyncio.Task[Any] | None = None

    def on_abort() -> None:
        if proc.returncode is None:
            proc.terminate()

    if signal is not None:
        abort_task = asyncio.create_task(signal.wait())
        abort_task.add_done_callback(lambda _: on_abort())

    try:
        stdout = proc.stdout
        stderr = proc.stderr
        assert stdout is not None and stderr is not None

        async def read_all(reader: asyncio.StreamReader) -> list[str]:
            chunks: list[str] = []
            while True:
                line = await reader.readline()
                if not line:
                    break
                chunks.append(line.decode("utf-8", errors="replace"))
            return chunks

        stdout_chunks, stderr_chunks = await asyncio.gather(
            read_all(stdout), read_all(stderr)
        )
        line_buffer = ""
        for text in stdout_chunks + stderr_chunks:
            line_buffer += text
            while "\n" in line_buffer:
                out, line_buffer = line_buffer.split("\n", 1)
                yield out.rstrip("\n")
        if line_buffer:
            yield line_buffer.rstrip("\n")
    finally:
        if abort_task is not None and not abort_task.done():
            abort_task.cancel()
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()


class DefaultSpawner:
    def spawn(
        self, cmd: str, args: list[str], opts: dict[str, Any]
    ) -> AsyncIterator[str]:
        return _default_spawner_impl(cmd, args, opts)


default_spawner = DefaultSpawner()


@dataclass(frozen=True)
class ComposePsRow:
    name: str
    service: str
    state: str
    health: str | None = None


class BoundComposeRunner:
    """A compose runner bound to one stack + yaml path."""

    def __init__(
        self,
        stack_name: str,
        yaml_path: str,
        cwd: str,
        spawner: Spawner,
    ) -> None:
        self.stack_name = stack_name
        self.yaml_path = yaml_path
        self.cwd = cwd
        self.spawner = spawner

    def base_args(self) -> list[str]:
        return [
            "compose",
            "-p",
            self.stack_name,
            "--project-directory",
            self.cwd,
            "-f",
            self.yaml_path,
        ]

    async def up(
        self, *, detach: bool = False, scale: dict[str, int] | None = None
    ) -> AsyncIterator[str]:
        args = self.base_args() + ["up"]
        if detach:
            args.append("-d")
        for svc, n in sorted((scale or {}).items()):
            args.extend(["--scale", f"{svc}={n}"])
        async for line in self.spawner.spawn("docker", args, {"cwd": self.cwd}):
            yield line

    async def down(self, *, volumes: bool = False) -> AsyncIterator[str]:
        args = self.base_args() + ["down"]
        if volumes:
            args.append("-v")
        async for line in self.spawner.spawn("docker", args, {"cwd": self.cwd}):
            yield line

    async def ps(self, *, json: bool = False) -> list[ComposePsRow]:
        args = self.base_args() + ["ps"]
        if json:
            args.extend(["--format", "json"])
        rows: list[ComposePsRow] = []
        async for line in self.spawner.spawn("docker", args, {"cwd": self.cwd}):
            line = line.strip()
            if not line:
                continue
            try:
                data = json_module.loads(line)
                rows.append(
                    ComposePsRow(
                        name=data["Name"],
                        service=data["Service"],
                        state=data["State"],
                        health=data.get("Health"),
                    )
                )
            except Exception:  # noqa: BLE001
                pass
        return rows

    async def logs(
        self,
        *,
        service: str | None = None,
        tail_lines: int | None = None,
        follow: bool = False,
        since: str | None = None,
        signal: Any | None = None,
    ) -> AsyncIterator[str]:
        args = self.base_args() + ["logs"]
        if follow:
            args.append("-f")
        if tail_lines is not None:
            args.extend(["--tail", str(tail_lines)])
        if since is not None:
            args.extend(["--since", since])
        if service is not None:
            args.append(service)
        async for line in self.spawner.spawn(
            "docker", args, {"cwd": self.cwd, "signal": signal}
        ):
            yield line


class ComposeRunner:
    """Factory for ``BoundComposeRunner``."""

    def __init__(self, cwd: str, spawner: Spawner | None = None) -> None:
        self.cwd = cwd
        self.spawner = spawner if spawner is not None else default_spawner

    def for_stack(self, stack_name: str, yaml_path: str) -> BoundComposeRunner:
        return BoundComposeRunner(stack_name, yaml_path, self.cwd, self.spawner)


__all__ = [
    "BoundComposeRunner",
    "ComposePsRow",
    "ComposeRunner",
    "DefaultSpawner",
    "Spawner",
    "default_spawner",
]
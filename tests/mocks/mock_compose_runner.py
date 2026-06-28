"""Mock compose runner for tool tests.

Parity: ``tests/mocks/mockComposeRunner.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from docker_agent.services.docker.compose_runner import ComposePsRow


class MockBoundRunner:
    def __init__(self, stack_name: str, yaml_path: str, cwd: str) -> None:
        self.stack_name = stack_name
        self.yaml_path = yaml_path
        self.cwd = cwd
        self.spawned_args = [
            "compose",
            "-p",
            stack_name,
            "--project-directory",
            cwd,
            "-f",
            yaml_path,
        ]
        self.up_calls: list[dict[str, Any]] = []
        self.down_calls: list[dict[str, Any]] = []
        self.stop_calls: list[dict[str, Any]] = []
        self.ps_calls: list[dict[str, Any]] = []
        self.logs_calls: list[dict[str, Any]] = []
        self.last_exit_code = 0
        self.ps_rows: list[ComposePsRow] | None = None
        self._logs_impl: Callable[..., AsyncIterator[str]] | None = None

    async def up(
        self, *, detach: bool = False, scale: dict[str, int] | None = None
    ) -> AsyncIterator[str]:
        self.up_calls.append({"detach": detach, "scale": scale})
        yield f"up: {self.stack_name}\n"
        self.last_exit_code = 0

    async def down(self, *, volumes: bool = False) -> AsyncIterator[str]:
        self.down_calls.append({"volumes": volumes})
        yield f"down: {self.stack_name}\n"
        self.last_exit_code = 0

    async def stop(self, *, services: list[str] | None = None) -> AsyncIterator[str]:
        self.stop_calls.append({"services": services})
        target = ", ".join(services) if services else "all"
        yield f"stop: {self.stack_name} ({target})\n"
        self.last_exit_code = 0

    async def ps(self, *, json: bool = False) -> list[ComposePsRow]:
        self.ps_calls.append({"json": json})
        return list(self.ps_rows or [])

    async def logs(
        self,
        *,
        service: str | None = None,
        tail_lines: int | None = None,
        follow: bool = False,
        since: str | None = None,
        signal: Any | None = None,
    ) -> AsyncIterator[str]:
        self.logs_calls.append(
            {
                "service": service,
                "tail_lines": tail_lines,
                "follow": follow,
                "since": since,
                "signal": signal,
            }
        )
        if self._logs_impl is not None:
            async for line in self._logs_impl(
                service=service,
                tail_lines=tail_lines,
                follow=follow,
                since=since,
                signal=signal,
            ):
                yield line
            self.last_exit_code = 0
            return
        yield ""
        self.last_exit_code = 0

    def set_running_services(self, service_names: list[str]) -> None:
        self.ps_rows = [
            ComposePsRow(
                name=f"{self.stack_name}-{svc}-1",
                service=svc,
                state="running",
            )
            for svc in service_names
        ]


class MockComposeRunner:
    def __init__(self, cwd: str = "/cwd") -> None:
        self.cwd = cwd
        self.for_stack_calls: list[dict[str, str]] = []
        self._bound: dict[str, MockBoundRunner] = {}
        self.on_bound_runner_created: Callable[[MockBoundRunner], None] | None = None

    def for_stack(self, stack_name: str, yaml_path: str) -> MockBoundRunner:
        self.for_stack_calls.append(
            {"stack_name": stack_name, "yaml_path": yaml_path}
        )
        existing = self._bound.get(stack_name)
        if existing is not None:
            return existing
        runner = MockBoundRunner(stack_name, yaml_path, self.cwd)
        self._bound[stack_name] = runner
        if self.on_bound_runner_created is not None:
            self.on_bound_runner_created(runner)
        return runner

    def bound_for(self, stack_name: str) -> MockBoundRunner:
        bound = self._bound.get(stack_name)
        if bound is None:
            raise KeyError(f"No bound runner for stack {stack_name}")
        return bound


__all__ = ["MockBoundRunner", "MockComposeRunner"]
"""apply_stack tool.

Parity: ``src/tools/applyStack.ts``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docker_agent.config import stack_state_yaml_path, stack_states_dir
from docker_agent.services.docker.compose_runner import BoundComposeRunner, ComposePsRow
from docker_agent.services.docker.git_guard import check_env_file_git_status
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.state.state_store import HistoryEvent
from docker_agent.tool import ToolContext, ToolDone, ToolProgress
from docker_agent.tools.check_port_conflict import parse_published_ports
from docker_agent.tools.shared.config_files import find_invalid_file_binds
from docker_agent.tools.shared.image_validation import validate_images_for_tool
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.tools.shared.yaml_round_trip import validate_yaml_round_trip
from docker_agent.types.stack import StackDefinition

HEALTH_DEADLINE_MS_DEFAULT = 120_000
POLL_INTERVAL_MS_DEFAULT = 2_000
FAILURE_LOG_TAIL = 15
TERMINAL_STATES = frozenset({"exited", "dead"})
POPULAR_HTTP_PORTS = frozenset({80, 8080, 3000, 3001, 5000, 8000, 9000, 9001})


class ApplyStackInput(BaseModel):
    stack_name: str = Field(alias="stackName")
    compose_yaml: str = Field(alias="composeYaml")
    scale_overrides: dict[str, int] | None = Field(default=None, alias="scaleOverrides")

    model_config = ConfigDict(populate_by_name=True)


class ApplyStackResult(BaseModel):
    ok: bool
    exit_code: int = Field(alias="exitCode")
    yaml_path: str = Field(alias="yamlPath")
    error_output: str | None = Field(default=None, alias="errorOutput")
    healthy: bool | None = None
    unhealthy_services: list[str] | None = Field(default=None, alias="unhealthyServices")
    running_services: list[str] | None = Field(default=None, alias="runningServices")

    model_config = ConfigDict(populate_by_name=True)


@dataclass(frozen=True)
class UnhealthyService:
    service: str
    status: str


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _unhealthy_status(row: ComposePsRow | None) -> str | None:
    if row is None:
        return "not created"
    if row.health is not None:
        return None if row.health == "healthy" else f"health: {row.health}"
    return None if row.state == "running" else row.state


async def verify_health(
    bound: BoundComposeRunner,
    expected_services: list[str],
    deadline_ms: int,
    abort: asyncio.Event,
) -> dict[str, object]:
    deadline = time.monotonic() + deadline_ms / 1000
    while True:
        if abort.is_set():
            return {
                "healthy": False,
                "unhealthy": [
                    UnhealthyService(service=service, status="aborted")
                    for service in expected_services
                ],
            }
        rows: list[ComposePsRow] = []
        with contextlib.suppress(Exception):
            rows = await bound.ps(json=True)

        unhealthy: list[UnhealthyService] = []
        crashed = False
        for service in expected_services:
            row = next((r for r in rows if r.service == service), None)
            status = _unhealthy_status(row)
            if status is None:
                continue
            unhealthy.append(UnhealthyService(service=service, status=status))
            if row is not None and row.state.lower() in TERMINAL_STATES:
                crashed = True

        if not unhealthy:
            return {"healthy": True, "unhealthy": []}
        if crashed:
            return {"healthy": False, "unhealthy": unhealthy}
        if time.monotonic() >= deadline:
            return {"healthy": False, "unhealthy": unhealthy}
        await asyncio.sleep(POLL_INTERVAL_MS_DEFAULT / 1000)


async def _collect_failure_logs(
    bound: BoundComposeRunner,
    services: list[str],
    secret_keys: set[str],
) -> str:
    sections: list[str] = []
    for svc in services:
        buf = ""
        try:
            async for line in bound.logs(service=svc, tail_lines=FAILURE_LOG_TAIL):
                buf += line
        except Exception:  # noqa: BLE001
            continue
        lines = [line for line in buf.split("\n") if line.strip()]
        if not lines:
            continue
        scrubbed = "\n".join(
            scrub_line(line, secret_keys).rstrip() for line in lines[-FAILURE_LOG_TAIL:]
        )
        sections.append(f"--- {svc} ---\n{scrubbed}")
    return "\n\n".join(sections)


def _stack_env_files(definition: StackDefinition) -> list[str]:
    env_files: set[str] = set()
    for spec in definition.services.values():
        for env_file in spec.env_file or []:
            env_files.add(env_file)
    return sorted(env_files)


async def _probe_http_port(url: str, abort: asyncio.Event) -> dict[str, object]:
    max_retries = 3
    timeout_seconds = 3.0

    for attempt in range(1, max_retries + 1):
        if abort.is_set():
            return {"success": False, "message": "Aborted"}
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Docker-Agent-HTTP-Probe"},
                )
                body_text = response.text[:10240]
                lowered = body_text.lower()

                if response.status_code == 500:
                    if any(
                        token in lowered
                        for token in (
                            "database connection",
                            "connection refused",
                            "access denied",
                            "establishing a database connection",
                        )
                    ):
                        return {
                            "success": False,
                            "message": "HTTP 500: Database connection error detected",
                        }
                    return {"success": False, "message": "HTTP status 500"}

                if any(
                    token in lowered
                    for token in (
                        "error establishing a database connection",
                        "database connection error",
                        "connection refused",
                    )
                ):
                    return {
                        "success": False,
                        "message": "Database connection error page detected",
                    }
                return {"success": True}
        except Exception as err:  # noqa: BLE001
            if attempt == max_retries:
                return {
                    "success": True,
                    "message": f"Inconclusive: {err}",
                }
            await asyncio.sleep(2)
    return {"success": True, "message": "Inconclusive: max retries reached without success"}


async def _verify_http_services(
    definition: StackDefinition,
    abort: asyncio.Event,
) -> dict[str, object]:
    failed_services: list[str] = []
    last_error: str | None = None

    for service_name, spec in definition.services.items():
        for port_mapping in spec.ports or []:
            published = parse_published_ports(port_mapping)
            if not published:
                continue
            port_bind = published[0]
            if (
                port_bind.protocol == "tcp"
                and port_bind.container_port in POPULAR_HTTP_PORTS
            ):
                probe = await _probe_http_port(
                    f"http://localhost:{port_bind.host_port}",
                    abort,
                )
                if not probe.get("success"):
                    failed_services.append(service_name)
                    last_error = str(probe.get("message"))

    return {
        "ok": not failed_services,
        "failed_services": failed_services,
        "error": last_error,
    }


async def _running_service_names(bound: BoundComposeRunner) -> list[str] | None:
    try:
        rows = await bound.ps(json=True)
        running = [row.service for row in rows if row.state == "running"]
        return running or None
    except Exception:  # noqa: BLE001
        return None


def _parse_stack_definition(raw: object, source: str) -> StackDefinition:
    try:
        return StackDefinition.model_validate(raw)
    except ValidationError as err:
        issues = "; ".join(
            f"{'/'.join(str(x) for x in issue['loc'])}: {issue['msg']}"
            for issue in err.errors()
        )
        raise ValueError(f"Invalid stack state at {source}: {issues}") from err


class _ApplyStackTool:
    name = "apply_stack"
    description = "Apply a planned stack: write YAML, run Compose up via ComposeRunner."
    input_schema = ApplyStackInput
    category = "high-level"

    def needs_permission(self, _input: ApplyStackInput) -> bool:
        return True

    async def call(
        self, input: ApplyStackInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yaml_path = stack_state_yaml_path(input.stack_name, ctx.cwd)

        try:
            parsed = yaml.safe_load(input.compose_yaml)
            definition = _parse_stack_definition(parsed, "apply_stack input")
        except Exception as err:  # noqa: BLE001
            yield ToolDone(
                ApplyStackResult(
                    ok=False,
                    exit_code=1,
                    yaml_path=yaml_path,
                    error_output=f"YAML round-trip validation failed: {err}",
                )
            )
            return

        image_validation = await validate_images_for_tool(
            [spec.image for spec in definition.services.values()],
            ctx,
        )
        if image_validation.error:
            yield ToolDone(
                ApplyStackResult(
                    ok=False,
                    exit_code=1,
                    yaml_path=yaml_path,
                    error_output=image_validation.error,
                )
            )
            return
        for warning in image_validation.warnings:
            yield ToolProgress(msg=warning)

        git_status = await check_env_file_git_status(_stack_env_files(definition), ctx.cwd)
        if git_status.refusals:
            yield ToolDone(
                ApplyStackResult(
                    ok=False,
                    exit_code=1,
                    yaml_path=yaml_path,
                    error_output="\n".join(
                        f"{file} is tracked by git. Run 'git rm --cached {file}' first."
                        for file in git_status.refusals
                    ),
                )
            )
            return
        for file in git_status.warnings:
            yield ToolProgress(
                msg=(
                    f"warning: {file} is neither tracked nor ignored. "
                    "Add '.env*' to .gitignore to prevent accidental commit."
                )
            )

        invalid_binds = find_invalid_file_binds(definition.services, ctx.cwd)
        if invalid_binds:
            lines = "\n".join(
                f"  - {bind['path']} ({bind['service']}): {bind['reason']}"
                for bind in invalid_binds
            )
            yield ToolDone(
                ApplyStackResult(
                    ok=False,
                    exit_code=1,
                    yaml_path=yaml_path,
                    error_output=(
                        "Refusing to start: every file bind-mount source must be a real file "
                        "before 'compose up' (Docker auto-creates a directory otherwise). "
                        "Provide the file content via configFiles, or create the files on disk:\n"
                        f"{lines}"
                    ),
                )
            )
            return

        yield ToolProgress(msg=f"Writing stack YAML for {input.stack_name}...")
        Path(stack_states_dir(ctx.cwd)).mkdir(parents=True, exist_ok=True)
        ctx.state_store.write(input.stack_name, definition)

        yaml_text = yaml.safe_dump(
            definition.model_dump(by_alias=True, exclude_none=True),
            sort_keys=False,
        )
        yaml_check = validate_yaml_round_trip(yaml_text)
        if not yaml_check.ok:
            yield ToolDone(
                ApplyStackResult(
                    ok=False,
                    exit_code=1,
                    yaml_path=yaml_path,
                    error_output=f"YAML round-trip validation failed: {yaml_check.error}",
                )
            )
            return

        secret_keys = collect_secret_keys(
            input.stack_name,
            SecretKeysContext(ctx.cwd, ctx.state_store),
        )

        yield ToolProgress(msg="Acquiring stack lock...")
        release = ctx.state_store.acquire_lock(input.stack_name, timeout_ms=30_000)

        try:
            yield ToolProgress(msg="Running Compose up -d...")
            bound = ctx.compose_runner.for_stack(input.stack_name, yaml_path)
            captured = ""
            async for line in bound.up(detach=True, scale=input.scale_overrides):
                captured += line
                scrubbed = scrub_line(line, secret_keys)
                yield ToolProgress(msg=scrubbed.rstrip())
            exit_code = getattr(bound, "last_exit_code", 0)

            ctx.state_store.append_history(
                HistoryEvent(
                    ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    session_id="unknown",
                    stack_name=input.stack_name,
                    action="apply",
                    details={"exitCode": exit_code},
                )
            )

            if exit_code != 0:
                yield ToolDone(
                    ApplyStackResult(
                        ok=False,
                        exit_code=exit_code,
                        yaml_path=yaml_path,
                        error_output=captured,
                        running_services=await _running_service_names(bound),
                    )
                )
                return

            expected_services = list(definition.services.keys())
            raw_deadline = (
                ctx.health_check_deadline_ms
                if ctx.health_check_deadline_ms is not None
                else HEALTH_DEADLINE_MS_DEFAULT
            )
            deadline_ms = (
                raw_deadline
                if ctx.health_check_deadline_ms is not None
                else _clamp(raw_deadline, 10_000, 600_000)
            )

            yield ToolProgress(msg="Waiting for services to become healthy...")
            health_result = await verify_health(
                bound,
                expected_services,
                deadline_ms,
                ctx.abort_signal,
            )

            if not health_result["healthy"]:
                unhealthy = health_result["unhealthy"]
                assert isinstance(unhealthy, list)
                failed_names = [item.service for item in unhealthy]
                logs = await _collect_failure_logs(bound, failed_names, secret_keys)
                yield ToolDone(
                    ApplyStackResult(
                        ok=False,
                        exit_code=0,
                        yaml_path=yaml_path,
                        healthy=False,
                        unhealthy_services=[
                            f"{item.service} ({item.status})" for item in unhealthy
                        ],
                        running_services=await _running_service_names(bound),
                        error_output=logs or None,
                    )
                )
                return

            yield ToolProgress(msg="Running post-deploy HTTP probe verification...")
            http_check = await _verify_http_services(definition, ctx.abort_signal)
            if not http_check["ok"]:
                failed = http_check["failed_services"]
                assert isinstance(failed, list)
                logs = await _collect_failure_logs(
                    bound,
                    [str(name) for name in failed],
                    secret_keys,
                )
                yield ToolDone(
                    ApplyStackResult(
                        ok=False,
                        exit_code=0,
                        yaml_path=yaml_path,
                        healthy=False,
                        unhealthy_services=[
                            f"{service} (HTTP probe failed: {http_check['error']})"
                            for service in failed
                        ],
                        running_services=await _running_service_names(bound),
                        error_output=logs or None,
                    )
                )
                return

            last_applied = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            updated_meta = definition.x_docker_agent.model_copy(
                update={"last_applied": last_applied}
            )
            ctx.state_store.write(
                input.stack_name,
                definition.model_copy(update={"x_docker_agent": updated_meta}),
            )
            yield ToolDone(
                ApplyStackResult(
                    ok=True,
                    exit_code=exit_code,
                    yaml_path=yaml_path,
                    healthy=True,
                    unhealthy_services=[],
                )
            )
        finally:
            release()


apply_stack = _ApplyStackTool()

__all__ = [
    "ApplyStackInput",
    "ApplyStackResult",
    "UnhealthyService",
    "apply_stack",
    "verify_health",
]
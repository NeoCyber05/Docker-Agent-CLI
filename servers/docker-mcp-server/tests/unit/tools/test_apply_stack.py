"""Parity tests for apply_stack."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from tool_helpers import drain, drain_with_progress, make_ctx

from docker_mcp_server.config import stack_state_yaml_path
from docker_mcp_server.services.docker.image_validator import ImageValidationResult
from docker_mcp_server.tools import apply_stack as apply_stack_module
from docker_mcp_server.tools.apply_stack import ApplyStackInput, apply_stack, verify_health
from docker_mcp_server.tools.base import ToolProgress
from tests.mocks.mock_compose_runner import MockBoundRunner, MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine

WEBAPP_YAML = """x-docker-agent:
  name: webapp
  createdAt: '2026-05-26T00:00:00.000Z'
  lastApplied: null
  intent: test
  provider: test
  generatedBy: test
  envFileSources: {}
services:
  web:
    image: nginx:1.27
"""


async def _drain_verify_health(
    *args: object,
    **kwargs: object,
) -> tuple[list[ToolProgress], dict[str, object]]:
    progress: list[ToolProgress] = []
    result: dict[str, object] | None = None
    async for item in verify_health(*args, **kwargs):  # type: ignore[arg-type]
        if isinstance(item, ToolProgress):
            progress.append(item)
        else:
            result = item
    assert result is not None
    return progress, result


class FakeValidator:
    def __init__(self, results: list[ImageValidationResult]) -> None:
        self.results = results

    async def validate_image(self, image: str, *, signal=None) -> ImageValidationResult:
        return self.results[0]

    async def validate_images(self, images: list[str], *, signal=None):
        by_image = {r.image: r for r in self.results}
        return [by_image[img] for img in images]


def _invalid_image_validator(image: str) -> FakeValidator:
    return FakeValidator(
        [
            ImageValidationResult(
                image=image,
                status="invalid",
                source="registry",
                error="manifest not found",
                suggestion="postgres:17-alpine",
            )
        ]
    )


@pytest.mark.asyncio
async def test_apply_stack_aborts_on_malformed_yaml(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    result = await drain(
        apply_stack.call(
            ApplyStackInput(
                stack_name="badyaml",
                compose_yaml="this is not: valid: yaml: [unclosed",
            ),
            ctx,
        )
    )
    assert result.ok is False
    assert result.error_output is not None
    assert "YAML" in result.error_output
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_apply_stack_writes_yaml_and_runs_compose_up(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    result = await drain(
        apply_stack.call(
            ApplyStackInput(
                stack_name="webapp",
                compose_yaml=WEBAPP_YAML,
                scale_overrides={"web": 2},
            ),
            ctx,
        )
    )

    assert result.ok is True
    assert Path(yaml_path).exists()
    assert runner.for_stack_calls[0]["stack_name"] == "webapp"
    assert runner.for_stack_calls[0]["yaml_path"] == yaml_path
    assert runner.bound_for("webapp").cwd == str(tmp_project)
    assert runner.bound_for("webapp").up_calls == [{"detach": True, "scale": {"web": 2}}]
    stored = ctx.state_store.read("webapp")
    assert stored is not None
    assert stored.x_docker_agent.last_applied is not None


@pytest.mark.asyncio
async def test_apply_stack_history_uses_session_id(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = replace(
        make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner),
        session_id="sess-apply",
    )
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    with patch.object(
        ctx.state_store, "append_history", wraps=ctx.state_store.append_history
    ) as append_history:
        result = await drain(
            apply_stack.call(
                ApplyStackInput(stack_name="webapp", compose_yaml=WEBAPP_YAML),
                ctx,
            )
        )

    assert result.ok is True
    apply_events = [
        call.args[0] for call in append_history.call_args_list if call.args[0].action == "apply"
    ]
    assert apply_events
    assert apply_events[0].session_id == "sess-apply"


@pytest.mark.asyncio
async def test_apply_stack_refuses_tracked_env_file(tmp_project: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_project, check=True, capture_output=True)
    env_file = tmp_project / ".env.api"
    env_file.write_text("API_KEY=tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", ".env.api"], cwd=tmp_project, check=True, capture_output=True)

    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml = WEBAPP_YAML.replace(
        "    image: nginx:1.27",
        "    image: nginx:1.27\n    env_file:\n      - .env.api",
    )

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is False
    assert result.error_output is not None
    assert ".env.api is tracked by git" in result.error_output
    assert runner.for_stack_calls == []


@pytest.mark.asyncio
async def test_apply_stack_scrubs_secret_output(tmp_project: Path) -> None:
    secrets_dir = tmp_project / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    secret_file = secrets_dir / "webapp-web.env"
    secret_file.write_text("API_KEY=leakvalue\n", encoding="utf-8")

    class SecretEmittingRunner(MockComposeRunner):
        def for_stack(self, stack_name: str, yaml_path: str) -> MockBoundRunner:
            bound = super().for_stack(stack_name, yaml_path)

            async def custom_up(**_kwargs: Any):
                yield "API_KEY=leakvalue\n"
                bound.last_exit_code = 0

            bound.up = custom_up  # type: ignore[method-assign, assignment]
            bound.set_running_services(["web"])
            return bound

    runner = SecretEmittingRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml = WEBAPP_YAML.replace(
        "    image: nginx:1.27",
        "    image: nginx:1.27\n    env_file:\n      - ./.docker-agent/secrets/webapp-web.env",
    )

    progress, _ = await drain_with_progress(
        apply_stack.call(
            ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
            ctx,
        )
    )

    joined = "\n".join(item.msg for item in progress)
    assert "API_KEY=***" in joined
    assert "leakvalue" not in joined


@pytest.mark.asyncio
async def test_apply_stack_rejects_invalid_images(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.image_validator = _invalid_image_validator("postgres:99-alpine")  # type: ignore[assignment]
    yaml = WEBAPP_YAML.replace("nginx:1.27", "postgres:99-alpine").replace(
        "name: webapp", "name: bad"
    )

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="bad", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is False
    assert result.exit_code == 1
    assert result.error_output is not None
    assert "postgres:99-alpine" in result.error_output
    assert runner.for_stack_calls == []
    assert ctx.state_store.read("bad") is None


@pytest.mark.asyncio
async def test_apply_stack_returns_running_services_on_partial_up_failure(
    tmp_project: Path,
) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("partial", str(tmp_project))
    pre_created = runner.for_stack("partial", yaml_path)

    async def failing_up(**_kwargs: Any):
        yield "Creating service web... done\n"
        yield "Creating service db... error\n"
        pre_created.last_exit_code = 1

    pre_created.up = failing_up  # type: ignore[method-assign, assignment]
    pre_created.ps_rows = [pre_created.ps_rows[0]] if pre_created.ps_rows else []
    from docker_mcp_server.services.docker.compose_runner import ComposePsRow

    pre_created.ps_rows = [
        ComposePsRow(name="partial-web-1", service="web", state="running")
    ]
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML.replace("name: webapp", "name: partial") + (
        "  db:\n    image: postgres:16-alpine\n"
    )

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="partial", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is False
    assert result.exit_code == 1
    assert result.running_services == ["web"]


@pytest.mark.asyncio
async def test_apply_stack_returns_running_services_when_unhealthy(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    ctx.health_check_deadline_ms = 0
    yaml_path = stack_state_yaml_path("mixed", str(tmp_project))
    pre_created = runner.for_stack("mixed", yaml_path)
    from docker_mcp_server.services.docker.compose_runner import ComposePsRow

    pre_created.ps_rows = [
        ComposePsRow(name="mixed-web-1", service="web", state="running"),
        ComposePsRow(name="mixed-db-1", service="db", state="exited"),
    ]
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML.replace("name: webapp", "name: mixed") + (
        "  db:\n    image: postgres:16-alpine\n"
    )

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="mixed", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is False
    assert result.healthy is False
    assert any("db" in item for item in (result.unhealthy_services or []))
    assert result.running_services == ["web"]


@pytest.mark.asyncio
async def test_apply_stack_success_omits_running_services(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("ok", str(tmp_project))
    pre_created = runner.for_stack("ok", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML.replace("name: webapp", "name: ok")

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="ok", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is True
    assert result.running_services is None


@pytest.mark.asyncio
async def test_apply_stack_http_probe_success(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML + "    ports:\n      - \"8080:80\"\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OK")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    class PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = PatchedClient  # type: ignore[misc]
    try:
        result = await drain(
            apply_stack.call(
                ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
                ctx,
            )
        )
    finally:
        httpx.AsyncClient = original_client  # type: ignore[misc]

    assert result.ok is True
    assert result.healthy is True


@pytest.mark.asyncio
async def test_apply_stack_http_probe_failure(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML + "    ports:\n      - \"8080:80\"\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Database connection error")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    class PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = PatchedClient  # type: ignore[misc]
    try:
        result = await drain(
            apply_stack.call(
                ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
                ctx,
            )
        )
    finally:
        httpx.AsyncClient = original_client  # type: ignore[misc]

    assert result.ok is False
    assert result.healthy is False
    assert any(
        "web (HTTP probe failed: HTTP 500: Database connection error detected)"
        in item
        for item in (result.unhealthy_services or [])
    )


@pytest.mark.asyncio
async def test_apply_stack_http_probe_inconclusive_does_not_fail(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web"])
    runner.for_stack_calls.clear()

    yaml = WEBAPP_YAML + "    ports:\n      - \"8080:80\"\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connect timeout")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    class PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = PatchedClient  # type: ignore[misc]
    try:
        result = await drain(
            apply_stack.call(
                ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
                ctx,
            )
        )
    finally:
        httpx.AsyncClient = original_client  # type: ignore[misc]

    assert result.ok is True
    assert result.healthy is True
    assert result.warnings is not None
    assert any("Inconclusive" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_apply_stack_log_scan_warns_on_db_connection_error(tmp_project: Path) -> None:
    runner = MockComposeRunner(str(tmp_project))
    ctx = make_ctx(tmp_project, docker_engine=MockDockerEngine(), compose_runner=runner)
    yaml_path = stack_state_yaml_path("webapp", str(tmp_project))
    pre_created = runner.for_stack("webapp", yaml_path)
    pre_created.set_running_services(["web", "db"])
    runner.for_stack_calls.clear()

    async def logs_with_db_error(**kwargs: Any):
        service = kwargs.get("service")
        if service == "db":
            yield "FATAL: password authentication failed for user \"postgres\"\n"
        else:
            yield "nginx started\n"

    pre_created._logs_impl = logs_with_db_error  # type: ignore[method-assign]

    yaml = WEBAPP_YAML.replace("name: webapp", "name: webapp") + (
        "  db:\n    image: postgres:16-alpine\n"
    )

    result = await drain(
        apply_stack.call(
            ApplyStackInput(stack_name="webapp", compose_yaml=yaml),
            ctx,
        )
    )

    assert result.ok is True
    assert result.healthy is True
    assert result.warnings is not None
    assert any("password authentication failed" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_verify_health_reports_running_service() -> None:
    class FakeBound:
        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            return [ComposePsRow(name="s-web-1", service="web", state="running")]

    progress, result = await _drain_verify_health(FakeBound(), ["web"], 10_000, asyncio.Event())
    assert result["healthy"] is True
    assert result["unhealthy"] == []
    assert progress
    assert any("Health" in item.msg and "web=running" in item.msg for item in progress)


@pytest.mark.asyncio
async def test_verify_health_treats_empty_health_as_running() -> None:
    """A container without a healthcheck reports Health='' and must not block."""

    class FakeBound:
        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            return [
                ComposePsRow(
                    name="s-wordpress-1",
                    service="wordpress",
                    state="running",
                    health="",
                )
            ]

    progress, result = await _drain_verify_health(
        FakeBound(), ["wordpress"], 60_000, asyncio.Event()
    )
    assert result["healthy"] is True
    assert result["unhealthy"] == []
    assert any("wordpress=running" in item.msg for item in progress)


@pytest.mark.asyncio
async def test_verify_health_fails_fast_on_exited_container() -> None:
    class FakeBound:
        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            return [
                ComposePsRow(name="s-web-1", service="web", state="running"),
                ComposePsRow(name="s-db-1", service="db", state="exited"),
            ]

    progress, result = await _drain_verify_health(
        FakeBound(), ["web", "db"], 60_000, asyncio.Event()
    )
    assert result["healthy"] is False
    unhealthy = result["unhealthy"]
    assert len(unhealthy) == 1
    assert unhealthy[0].service == "db"
    assert unhealthy[0].status == "exited"
    assert progress
    assert any("db=exited" in item.msg for item in progress)


@pytest.mark.asyncio
async def test_verify_health_fails_fast_on_unhealthy() -> None:
    class FakeBound:
        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            return [
                ComposePsRow(
                    name="s-db-1",
                    service="db",
                    state="running",
                    health="unhealthy",
                )
            ]

    with patch.object(apply_stack_module, "FAIL_FAST_GRACE_MS", 0):
        progress, result = await _drain_verify_health(
            FakeBound(), ["db"], 60_000, asyncio.Event()
        )

    assert result["healthy"] is False
    unhealthy = result["unhealthy"]
    assert len(unhealthy) == 1
    assert unhealthy[0].service == "db"
    assert unhealthy[0].status == "health: unhealthy"
    assert progress
    assert any("db=unhealthy" in item.msg for item in progress)


@pytest.mark.asyncio
async def test_verify_health_fails_fast_on_restart_loop() -> None:
    class FakeBound:
        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            return [
                ComposePsRow(name="s-web-1", service="web", state="restarting"),
            ]

    with patch.object(apply_stack_module, "RESTART_LOOP_THRESHOLD", 1):
        progress, result = await _drain_verify_health(
            FakeBound(), ["web"], 60_000, asyncio.Event()
        )

    assert result["healthy"] is False
    unhealthy = result["unhealthy"]
    assert len(unhealthy) == 1
    assert unhealthy[0].service == "web"
    assert unhealthy[0].status == "restarting"
    assert progress
    assert any("web=restarting" in item.msg for item in progress)


@pytest.mark.asyncio
async def test_verify_health_tolerates_transient_then_healthy() -> None:
    class FakeBound:
        def __init__(self) -> None:
            self.calls = 0

        async def ps(self, *, json: bool = False):
            from docker_mcp_server.services.docker.compose_runner import ComposePsRow

            self.calls += 1
            if self.calls == 1:
                return [ComposePsRow(name="s-web-1", service="web", state="restarting")]
            return [ComposePsRow(name="s-web-1", service="web", state="running")]

    with (
        patch.object(apply_stack_module, "FAIL_FAST_GRACE_MS", 15_000),
        patch.object(apply_stack_module, "RESTART_LOOP_THRESHOLD", 99),
        patch.object(apply_stack_module, "POLL_INTERVAL_MS_DEFAULT", 0),
    ):
        progress, result = await _drain_verify_health(
            FakeBound(), ["web"], 60_000, asyncio.Event()
        )

    assert result["healthy"] is True
    assert result["unhealthy"] == []
    assert progress
    assert any("web=restarting" in item.msg for item in progress)
    assert any("web=running" in item.msg for item in progress)



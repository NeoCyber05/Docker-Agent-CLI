"""Parity tests for get_health — mirrors getHealth.test.ts and computeStats.test.ts."""

from __future__ import annotations

import pytest

from docker_agent.services.docker.types import ContainerStats, ContainerSummary
from docker_agent.tools.base import ToolContext
from docker_agent.tools.get_health import compute_stats, get_health
from tests.unit.tools.conftest import drain_with_progress, make_ctx

_MB = 1024 * 1024

_GOOD_STATS = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 2]},
        "system_cpu_usage": 2000,
        "online_cpus": 2,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 100},
        "system_cpu_usage": 1000,
    },
    "memory_stats": {"usage": 50 * _MB, "limit": 100 * _MB},
}


def _ctx_with(engine: object, tmp_project) -> ToolContext:
    base = make_ctx(tmp_project)
    return ToolContext(
        cwd=base.cwd,
        state_store=base.state_store,
        docker_engine=engine,
        compose_runner=base.compose_runner,
        abort_signal=base.abort_signal,
    )


@pytest.mark.asyncio
async def test_requests_all_containers_with_project_label_filter(tmp_project) -> None:
    engine = _RecordingEngine()
    await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "web"}),
            _ctx_with(engine, tmp_project),
        )
    )
    assert engine.list_calls == [
        {"all": True, "filters": {"label": ["com.docker.compose.project=web"]}}
    ]


@pytest.mark.asyncio
async def test_maps_running_container_with_cpu_mem_and_no_crash_loop(
    tmp_project,
) -> None:
    engine = _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/web-1"],
            "State": "running",
            "Labels": {"com.docker.compose.service": "web"},
        },
        inspect={
            "Id": "c1",
            "Name": "/web-1",
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "Config": {"Image": "nginx", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": 0,
        },
        stats=_GOOD_STATS,
    )
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "web"}),
            _ctx_with(engine, tmp_project),
        )
    )
    assert len(result.containers) == 1
    row = result.containers[0]
    assert row.service == "web"
    assert row.status == "running"
    assert row.health == "healthy"
    assert row.cpu_percent == pytest.approx(20)
    assert row.mem_used_mb == pytest.approx(50)
    assert row.crash_loop is False
    assert result.crash_loops == []


@pytest.mark.asyncio
async def test_crash_loop_threshold_boundary(tmp_project) -> None:
    two = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(_restart_engine(2), tmp_project),
        )
    )
    assert two[1].containers[0].crash_loop is False

    three = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(_restart_engine(3), tmp_project),
        )
    )
    assert three[1].containers[0].crash_loop is True
    assert three[1].crash_loops == ["/db-1"]


@pytest.mark.asyncio
async def test_restarting_status_flags_crash_loop(tmp_project) -> None:
    engine = _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/w-1"],
            "State": "restarting",
            "Labels": {"com.docker.compose.service": "w"},
        },
        inspect={
            "Id": "c1",
            "Name": "/w-1",
            "State": {"Status": "restarting"},
            "Config": {"Image": "x", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": 0,
        },
        stats=_GOOD_STATS,
    )
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    assert result.containers[0].crash_loop is True


@pytest.mark.asyncio
async def test_returns_exited_container_with_null_cpu_mem(tmp_project) -> None:
    engine = _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/job-1"],
            "State": "exited",
            "Labels": {"com.docker.compose.service": "job"},
        },
        inspect={
            "Id": "c1",
            "Name": "/job-1",
            "State": {"Status": "exited"},
            "Config": {"Image": "x", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": 0,
        },
        stats_error=RuntimeError("no stats for stopped container"),
    )
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    row = result.containers[0]
    assert row.status == "exited"
    assert row.cpu_percent is None
    assert row.error


@pytest.mark.asyncio
async def test_inspect_failure_isolated(tmp_project) -> None:
    engine = _DualContainerEngine()
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    bad = next(row for row in result.containers if row.name == "/bad-1")
    ok = next(row for row in result.containers if row.name == "/ok-1")
    assert bad.error
    assert bad.status == "running"
    assert bad.restart_count == 0
    assert ok.error is None
    assert ok.health == "healthy"


@pytest.mark.asyncio
async def test_stats_failure_preserves_inspect_data(tmp_project) -> None:
    engine = _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/web-1"],
            "State": "running",
            "Labels": {"com.docker.compose.service": "web"},
        },
        inspect={
            "Id": "c1",
            "Name": "/web-1",
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "Config": {"Image": "x", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": 5,
        },
        stats_error=RuntimeError("stats unavailable"),
    )
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    row = result.containers[0]
    assert row.cpu_percent is None
    assert row.mem_used_mb is None
    assert row.health == "healthy"
    assert row.restart_count == 5
    assert row.crash_loop is True
    assert row.error


@pytest.mark.asyncio
async def test_first_sample_stats_yields_cpu_percent_null(tmp_project) -> None:
    engine = _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/web-1"],
            "State": "running",
            "Labels": {"com.docker.compose.service": "web"},
        },
        inspect={
            "Id": "c1",
            "Name": "/web-1",
            "State": {"Status": "running"},
            "Config": {"Image": "x", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": 0,
        },
        stats={
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 2000,
                "online_cpus": 1,
            },
            "memory_stats": {"usage": _MB, "limit": 2 * _MB},
        },
    )
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    assert result.containers[0].cpu_percent is None
    assert result.containers[0].mem_used_mb == pytest.approx(1)


@pytest.mark.asyncio
async def test_top_level_engine_failure_returns_error_result(tmp_project) -> None:
    engine = _FailingListEngine()
    _, result = await drain_with_progress(
        get_health.call(
            get_health.input_schema.model_validate({"stackName": "s"}),
            _ctx_with(engine, tmp_project),
        )
    )
    assert result.containers == []
    assert "docker daemon down" in (result.error or "")


def test_compute_stats_valid_sample() -> None:
    raw = ContainerStats.model_validate(_GOOD_STATS)
    result = compute_stats(raw)
    assert result.cpu_percent == pytest.approx(20)
    assert result.mem_used_mb == pytest.approx(50)
    assert result.mem_limit_mb == pytest.approx(100)
    assert result.mem_percent == pytest.approx(50)


def test_compute_stats_num_cpus_fallback_to_percpu_length() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300, "percpu_usage": [1, 2, 3, 4]},
                "system_cpu_usage": 2000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {},
        }
    )
    assert compute_stats(raw).cpu_percent == pytest.approx(80)


def test_compute_stats_null_cpu_when_precpu_absent() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 2000,
                "online_cpus": 1,
            },
            "memory_stats": {"usage": _MB, "limit": 2 * _MB},
        }
    )
    assert compute_stats(raw).cpu_percent is None


def test_compute_stats_null_cpu_when_system_cpu_usage_missing() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {"cpu_usage": {"total_usage": 200}, "online_cpus": 1},
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {},
        }
    )
    assert compute_stats(raw).cpu_percent is None


def test_compute_stats_null_cpu_when_system_delta_non_positive() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {},
        }
    )
    assert compute_stats(raw).cpu_percent is None


def test_compute_stats_mem_null_when_usage_or_limit_missing() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 2000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {"usage": _MB},
        }
    )
    result = compute_stats(raw)
    assert result.mem_used_mb is None
    assert result.mem_limit_mb is None
    assert result.mem_percent is None


def test_compute_stats_mem_null_when_limit_zero() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 2000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {"usage": _MB, "limit": 0},
        }
    )
    result = compute_stats(raw)
    assert result.mem_used_mb is None
    assert result.mem_limit_mb is None
    assert result.mem_percent is None


def test_compute_stats_num_cpus_fallback_to_one() -> None:
    raw = ContainerStats.model_validate(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 2000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {},
        }
    )
    assert compute_stats(raw).cpu_percent == pytest.approx(10)


class _RecordingEngine:
    def __init__(self) -> None:
        self.list_calls: list[dict] = []

    async def list_containers(
        self, *, all: bool = False, filters: dict | None = None
    ) -> list[ContainerSummary]:
        self.list_calls.append({"all": all, "filters": filters})
        return []

    async def inspect(self, _container_id: str):  # noqa: ANN202
        raise AssertionError("not called")

    async def stats(self, _container_id: str):  # noqa: ANN202
        raise AssertionError("not called")


class _SingleContainerEngine:
    def __init__(
        self,
        *,
        summary: dict,
        inspect: dict,
        stats: dict | None = None,
        stats_error: Exception | None = None,
    ) -> None:
        self.summary = ContainerSummary.model_validate(summary)
        self.inspect_data = inspect
        self.stats_data = stats
        self.stats_error = stats_error

    async def list_containers(
        self, *, all: bool = False, filters: dict | None = None
    ) -> list[ContainerSummary]:
        return [self.summary]

    async def inspect(self, _container_id: str):
        from docker_agent.services.docker.types import ContainerInspect

        return ContainerInspect.model_validate(self.inspect_data)

    async def stats(self, _container_id: str) -> ContainerStats:
        if self.stats_error is not None:
            raise self.stats_error
        return ContainerStats.model_validate(self.stats_data or _GOOD_STATS)


def _restart_engine(restart_count: int) -> _SingleContainerEngine:
    return _SingleContainerEngine(
        summary={
            "Id": "c1",
            "Names": ["/db-1"],
            "State": "running",
            "Labels": {"com.docker.compose.service": "db"},
        },
        inspect={
            "Id": "c1",
            "Name": "/db-1",
            "State": {"Status": "running"},
            "Config": {"Image": "postgres", "Env": [], "Labels": {}},
            "HostConfig": {"Binds": None, "PortBindings": {}},
            "NetworkSettings": {"Ports": {}},
            "RestartCount": restart_count,
        },
        stats=_GOOD_STATS,
    )


class _DualContainerEngine:
    async def list_containers(
        self, *, all: bool = False, filters: dict | None = None
    ) -> list[ContainerSummary]:
        return [
            ContainerSummary.model_validate(
                {
                    "Id": "bad",
                    "Names": ["/bad-1"],
                    "State": "running",
                    "Labels": {"com.docker.compose.service": "bad"},
                }
            ),
            ContainerSummary.model_validate(
                {
                    "Id": "ok",
                    "Names": ["/ok-1"],
                    "State": "running",
                    "Labels": {"com.docker.compose.service": "ok"},
                }
            ),
        ]

    async def inspect(self, container_id: str):
        from docker_agent.services.docker.types import ContainerInspect

        if container_id == "bad":
            raise RuntimeError("container vanished")
        return ContainerInspect.model_validate(
            {
                "Id": "ok",
                "Name": "/ok-1",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "Config": {"Image": "x", "Env": [], "Labels": {}},
                "HostConfig": {"Binds": None, "PortBindings": {}},
                "NetworkSettings": {"Ports": {}},
                "RestartCount": 0,
            }
        )

    async def stats(self, _container_id: str) -> ContainerStats:
        return ContainerStats.model_validate(_GOOD_STATS)


class _FailingListEngine:
    async def list_containers(
        self, *, all: bool = False, filters: dict | None = None
    ) -> list[ContainerSummary]:
        raise RuntimeError("docker daemon down")
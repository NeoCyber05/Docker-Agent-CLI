"""Tests for internal published-port conflict helpers."""

from __future__ import annotations

import pytest
from mocks.mock_compose_runner import MockComposeRunner
from mocks.mock_docker_engine import MockDockerEngine

from docker_agent.services.docker.types import ContainerSummary
from docker_agent.tools.base import ToolContext
from docker_agent.tools.shared.port_conflicts import (
    PublishedPort,
    check_port_conflicts,
    parse_published_ports,
)
from tests.unit.tools.conftest import make_ctx


def _inspect_with_ports(
    container_id: str, container_port: str, host_port: str
) -> dict[str, object]:
    return {
        "Id": container_id,
        "Name": f"/{container_id}",
        "State": {"Status": "running"},
        "Config": {"Image": "nginx", "Env": [], "Labels": {}},
        "HostConfig": {"Binds": None, "PortBindings": {}},
        "NetworkSettings": {
            "Ports": {
                container_port: [{"HostIp": "0.0.0.0", "HostPort": host_port}]
            }
        },
        "RestartCount": 0,
    }


def _make_ctx(engine: MockDockerEngine, tmp_project) -> ToolContext:
    base = make_ctx(tmp_project, docker_engine=engine)
    return ToolContext(
        cwd=base.cwd,
        state_store=base.state_store,
        docker_engine=engine,
        compose_runner=MockComposeRunner(str(tmp_project)),
        abort_signal=base.abort_signal,
    )


def _engine_with_published_port(
    *,
    container_id: str,
    project: str,
    host_port: str,
    container_port: str,
) -> MockDockerEngine:
    engine = MockDockerEngine()
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": container_id,
                "Names": [f"/{container_id}"],
                "State": "running",
                "Labels": {"com.docker.compose.project": project},
            }
        ).model_dump(by_alias=True)
    )
    engine.inspect_by_id[container_id] = _inspect_with_ports(
        container_id, container_port, host_port
    )
    return engine


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("80", []),
        (
            "8080:80",
            [PublishedPort("0.0.0.0", 8080, 80, "tcp")],
        ),
        (
            "127.0.0.1:5353:53/udp",
            [PublishedPort("127.0.0.1", 5353, 53, "udp")],
        ),
    ],
)
def test_parse_published_ports(value: str, expected: list[PublishedPort]) -> None:
    assert parse_published_ports(value) == expected


@pytest.mark.asyncio
async def test_reports_draft_and_running_container_conflicts(tmp_project) -> None:
    engine = MockDockerEngine()
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": "existing",
                "Names": ["/existing"],
                "State": "running",
                "Labels": {},
            }
        ).model_dump(by_alias=True)
    )
    engine.inspect_by_id["existing"] = _inspect_with_ports(
        "existing", "80/tcp", "8080"
    )

    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "app",
        {
            "api": ServiceSpec(image="example/api:1", ports=["8080:80"]),
            "admin": ServiceSpec(image="example/admin:1", ports=["8080:8080"]),
        },
        _make_ctx(engine, tmp_project),
    )

    assert result.ok is False
    assert {c.source for c in result.conflicts} == {"draft", "running"}


@pytest.mark.asyncio
async def test_ignores_bindings_owned_by_stack_being_updated(tmp_project) -> None:
    engine = _engine_with_published_port(
        container_id="own-web",
        project="app",
        host_port="8080",
        container_port="80/tcp",
    )
    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "app",
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["8080:80"])},
        _make_ctx(engine, tmp_project),
    )
    assert result.ok is True
    assert result.conflicts == []


@pytest.mark.asyncio
async def test_tcp_and_udp_on_same_host_port_do_not_conflict(tmp_project) -> None:
    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "dns",
        {
            "dnsTcp": ServiceSpec(image="example/dns:1", ports=["5353:53/tcp"]),
            "dnsUdp": ServiceSpec(image="example/dns:1", ports=["5353:53/udp"]),
        },
        _make_ctx(MockDockerEngine(), tmp_project),
    )
    assert result.ok is True


@pytest.mark.asyncio
async def test_accepts_numeric_host_port_from_docker_engine(tmp_project) -> None:
    engine = MockDockerEngine()
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": "existing",
                "Names": ["/existing"],
                "State": "running",
                "Labels": {},
            }
        ).model_dump(by_alias=True)
    )
    engine.inspect_by_id["existing"] = {
        "Id": "existing",
        "Name": "/existing",
        "State": {"Status": "running"},
        "Config": {"Image": "nginx", "Env": [], "Labels": {}},
        "HostConfig": {"Binds": None, "PortBindings": {}},
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": 8080}]}
        },
        "RestartCount": 0,
    }

    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "app",
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["9090:80"])},
        _make_ctx(engine, tmp_project),
    )

    assert result.ok is True
    assert result.docker_error is None


@pytest.mark.asyncio
async def test_returns_actionable_result_when_docker_engine_unavailable(
    tmp_project,
) -> None:
    class DockerUnavailableError(OSError):
        code = "ENOENT"

    engine = MockDockerEngine()
    engine.list_containers_error = DockerUnavailableError(
        "connect ENOENT //./pipe/docker_engine"
    )

    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "app",
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["8080:80"])},
        _make_ctx(engine, tmp_project),
    )

    assert result.ok is False
    assert result.conflicts == []
    assert result.invalid == []
    assert result.docker_error == {
        "code": "docker_engine_unavailable",
        "message": (
            "Docker Engine is unavailable. Start Docker Desktop or the Docker "
            "daemon, then retry."
        ),
    }


@pytest.mark.asyncio
async def test_skips_container_when_inspect_fails(tmp_project) -> None:
    class PartiallyBrokenEngine(MockDockerEngine):
        async def inspect(self, container_id: str):
            if container_id == "broken":
                raise RuntimeError("inspect failed")
            return await super().inspect(container_id)

    engine = PartiallyBrokenEngine()
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": "broken",
                "Names": ["/broken"],
                "State": "running",
                "Labels": {},
            }
        ).model_dump(by_alias=True)
    )
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": "healthy",
                "Names": ["/healthy"],
                "State": "running",
                "Labels": {},
            }
        ).model_dump(by_alias=True)
    )
    engine.inspect_by_id["healthy"] = _inspect_with_ports(
        "healthy", "80/tcp", "9090"
    )

    from docker_agent.types.stack import ServiceSpec

    result = await check_port_conflicts(
        "app",
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["9090:80"])},
        _make_ctx(engine, tmp_project),
    )

    assert result.ok is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflicts_with == "/healthy"

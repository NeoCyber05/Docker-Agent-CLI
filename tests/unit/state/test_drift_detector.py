"""Parity tests for drift_detector â€” mirrors src/state/driftDetector.ts."""

from pathlib import Path

import pytest

from docker_mcp_server.services.docker.types import ContainerInspect, ContainerSummary, EngineClient
from docker_mcp_server.state.drift_detector import detect_drift
from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _make_store(tmp_path: Path, stack_name: str, spec: ServiceSpec) -> StateStore:
    store = StateStore(str(tmp_path / ".docker-agent"))
    store.write(
        stack_name,
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
                name=stack_name,
                created_at="t",
                last_applied=None,
                intent="i",
                provider="g",
                generated_by="a",
                env_file_sources={},
            ),
            services={stack_name: spec},
        ),
    )
    return store


def _fake_container_inspect(
    *,
    image: str,
    cmd: list[str] | None,
    env: list[str],
    binds: list[str] | None,
    ports: dict[str, list[dict[str, str]] | None],
    service: str,
    status: str,
    container_id: str = "abc",
) -> ContainerInspect:
    return ContainerInspect.model_validate(
        {
            "Id": container_id,
            "Name": f"/{service}-1",
            "State": {"Status": status},
            "Config": {
                "Image": image,
                "Cmd": cmd,
                "Env": env,
                "Labels": {"com.docker.compose.service": service},
            },
            "HostConfig": {"Binds": binds, "PortBindings": {}},
            "NetworkSettings": {"Ports": ports},
            "RestartCount": 0,
        }
    )


class FakeEngineClient(EngineClient):
    def __init__(self, containers: list[ContainerInspect]) -> None:
        self._containers = containers

    async def list_containers(
        self, *, all: bool = False, filters: dict | None = None
    ) -> list[ContainerSummary]:
        return [
            ContainerSummary.model_validate(
                {
                    "Id": f"id-{i}",
                    "Names": [f"/svc-{i}"],
                    "State": "running",
                    "Labels": {},
                }
            )
            for i in range(len(self._containers))
        ]

    async def inspect(self, container_id: str) -> ContainerInspect:
        idx = int(container_id.split("-")[-1])
        return self._containers[idx]


@pytest.mark.asyncio
async def test_detect_drift_missing_definition(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    engine = FakeEngineClient([])
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "missing"
    assert diff.service_diffs == []


@pytest.mark.asyncio
async def test_detect_drift_in_sync(tmp_path: Path) -> None:
    store = _make_store(tmp_path, "web", ServiceSpec(image="nginx:1.27", scale=1))
    engine = FakeEngineClient(
        [
            _fake_container_inspect(
                image="nginx:1.27",
                cmd=None,
                env=[],
                binds=None,
                ports={},
                service="web",
                status="running",
            )
        ]
    )
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "in_sync"


@pytest.mark.asyncio
async def test_detect_drift_image_changed(tmp_path: Path) -> None:
    store = _make_store(tmp_path, "web", ServiceSpec(image="nginx:1.28"))
    engine = FakeEngineClient(
        [
            _fake_container_inspect(
                image="nginx:1.27",
                cmd=None,
                env=[],
                binds=None,
                ports={},
                service="web",
                status="running",
            )
        ]
    )
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "drift"
    assert any(c.field == "image" for c in diff.service_diffs[0].changes)


@pytest.mark.asyncio
async def test_detect_drift_extra_service(tmp_path: Path) -> None:
    store = _make_store(tmp_path, "web", ServiceSpec(image="nginx:1.27"))
    engine = FakeEngineClient(
        [
            _fake_container_inspect(
                image="nginx:1.27",
                cmd=None,
                env=[],
                binds=None,
                ports={},
                service="extra",
                status="running",
            )
        ]
    )
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "extra"


@pytest.mark.asyncio
async def test_detect_drift_missing_service(tmp_path: Path) -> None:
    store = _make_store(tmp_path, "web", ServiceSpec(image="nginx:1.27"))
    engine = FakeEngineClient([])
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "missing"


@pytest.mark.asyncio
async def test_detect_drift_ignores_duplicate_inspect_ports(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path,
        "web",
        ServiceSpec(image="wordpress:6", ports=["8080:80"]),
    )
    engine = FakeEngineClient(
        [
            _fake_container_inspect(
                image="wordpress:6",
                cmd=None,
                env=[],
                binds=None,
                ports={
                    "80/tcp": [
                        {"HostIp": "0.0.0.0", "HostPort": "8080"},
                        {"HostIp": "0.0.0.0", "HostPort": "8080"},
                    ]
                },
                service="web",
                status="running",
            )
        ]
    )
    diff = await detect_drift("web", store, engine, str(tmp_path))
    assert diff.status == "in_sync"
    assert diff.service_diffs[0].changes == []

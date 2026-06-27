"""Parity tests for remediate_drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from docker_agent.services.docker.types import ContainerInspect, ContainerSummary
from docker_agent.state.state_store import StateStore
from docker_agent.tools.remediate_drift import RemediateDriftInput, remediate_drift
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.unit.tools.conftest import drain, make_ctx


class FakeEngine:
    def __init__(self, *, image: str = "nginx:1.27") -> None:
        self.image = image

    async def list_containers(self, *, all=False, filters=None):
        return [
            ContainerSummary.model_validate(
                {
                    "Id": "id-1",
                    "Names": ["/web-1"],
                    "State": "running",
                    "Labels": {"com.docker.compose.project": "webapp"},
                }
            )
        ]

    async def inspect(self, container_id: str):
        return ContainerInspect.model_validate(
            {
                "Id": container_id,
                "Name": "/web-1",
                "State": {"Status": "running"},
                "Config": {
                    "Image": self.image,
                    "Env": [],
                    "Cmd": None,
                    "Labels": {"com.docker.compose.service": "web"},
                },
                "HostConfig": {"Binds": None},
                "NetworkSettings": {"Ports": {}},
                "RestartCount": 0,
            }
        )

    async def stats(self, container_id: str):
        return {}

    async def inspect_image(self, name_or_id: str):
        return None

    async def list_images(self, *, filters=None):
        return []

    async def pull_image(self, image: str, *, signal=None):
        yield ""


def _seed_stack(store: StateStore, name: str, *, image: str = "nginx:1.27") -> None:
    store.write(
        name,
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name=name,
                created_at="t",
                last_applied="t",
                intent="i",
                provider="g",
                generated_by="a",
                env_file_sources={},
            ),
            services={"web": ServiceSpec(image=image)},
        ),
    )


@pytest.mark.asyncio
async def test_remediate_drift_in_sync_is_not_remediable(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    _seed_stack(store, "webapp")
    ctx = make_ctx(
        tmp_project,
        docker_engine=FakeEngine(image="nginx:1.27"),
        compose_runner=MockComposeRunner(),
    )
    ctx.state_store = store

    result = await drain(
        remediate_drift.call(RemediateDriftInput(stack_name="webapp"), ctx)
    )

    assert result.remediable is False
    assert result.reason == "in_sync"
    assert result.desired_yaml == ""


@pytest.mark.asyncio
async def test_remediate_drift_without_desired_state_is_not_remediable(
    tmp_project: Path,
) -> None:
    ctx = make_ctx(tmp_project, docker_engine=FakeEngine(), compose_runner=MockComposeRunner())

    result = await drain(
        remediate_drift.call(RemediateDriftInput(stack_name="missing"), ctx)
    )

    assert result.remediable is False
    assert result.reason == "no desired state"


@pytest.mark.asyncio
async def test_remediate_drift_with_drift_is_remediable(tmp_project: Path) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    _seed_stack(store, "webapp", image="nginx:1.27")
    ctx = make_ctx(
        tmp_project,
        docker_engine=FakeEngine(image="nginx:1.28"),
        compose_runner=MockComposeRunner(),
    )
    ctx.state_store = store

    result = await drain(
        remediate_drift.call(RemediateDriftInput(stack_name="webapp"), ctx)
    )

    assert result.remediable is True
    assert "nginx:1.27" in result.desired_yaml
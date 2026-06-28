"""Parity tests for engine_client — mirrors src/services/docker/engineClient.ts."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from docker_agent.services.docker.engine_client import (
    _docker_list_payload,
    _load_docker_py,
    create_engine_client,
)
from docker_agent.services.docker.types import ImageInspect


class FakeDockerContainer:
    """Mimics docker-py Container: list data in _attrs, inspect via attrs."""

    def __init__(self, list_attrs: dict[str, Any], inspect_attrs: dict[str, Any]) -> None:
        self._attrs = list_attrs
        self._inspect_attrs = inspect_attrs

    @property
    def attrs(self) -> dict[str, Any]:
        return self._inspect_attrs


class FakeDockerClient:
    def __init__(self, containers: Any | None = None, images: Any | None = None) -> None:
        self.containers = containers or MagicMock()
        self.images = images or MagicMock()


@pytest.fixture
def fake_docker() -> FakeDockerClient:
    return FakeDockerClient()


@pytest.mark.asyncio
async def test_list_containers(fake_docker: FakeDockerClient) -> None:
    fake_docker.containers.list.return_value = [
        {
            "Id": "abc",
            "Names": ["/web"],
            "State": "running",
            "Labels": {"k": "v"},
        }
    ]
    engine = create_engine_client(fake_docker)
    rows = await engine.list_containers(all=True, filters={"label": ["x"]})
    assert len(rows) == 1
    assert rows[0].id == "abc"
    fake_docker.containers.list.assert_called_once_with(
        all=True, filters={"label": ["x"]}
    )


@pytest.mark.asyncio
async def test_list_containers_uses_list_attrs_not_inspect(fake_docker: FakeDockerClient) -> None:
    fake_docker.containers.list.return_value = [
        FakeDockerContainer(
            list_attrs={
                "Id": "abc",
                "Names": ["/web"],
                "State": "exited",
                "Labels": {"k": "v"},
            },
            inspect_attrs={
                "Id": "abc",
                "Name": "/web",
                "State": {"Status": "exited", "Running": False},
                "Config": {"Labels": {"k": "v"}},
            },
        )
    ]
    engine = create_engine_client(fake_docker)
    rows = await engine.list_containers(all=True)
    assert len(rows) == 1
    assert rows[0].state == "exited"


def test_docker_list_payload_prefers_attrs_over_inspect() -> None:
    item = FakeDockerContainer(
        list_attrs={"Id": "1", "Names": ["/a"], "State": "running", "Labels": {}},
        inspect_attrs={"Id": "1", "State": {"Status": "exited"}},
    )
    payload = _docker_list_payload(item)
    assert payload["State"] == "running"


@pytest.mark.asyncio
async def test_inspect_image_returns_model(fake_docker: FakeDockerClient) -> None:
    fake_docker.images.get.return_value = MagicMock(
        attrs={
            "Id": "sha:abc",
            "RepoTags": ["nginx:1.27"],
            "Size": 100,
            "Architecture": "amd64",
            "Os": "linux",
            "Created": "2024-01-01T00:00:00Z",
        }
    )
    engine = create_engine_client(fake_docker)
    img = await engine.inspect_image("nginx")
    assert isinstance(img, ImageInspect)
    assert img.id == "sha:abc"


@pytest.mark.asyncio
async def test_inspect_image_returns_none_on_404(fake_docker: FakeDockerClient) -> None:
    ImageNotFound = _load_docker_py().errors.ImageNotFound
    fake_docker.images.get.side_effect = ImageNotFound("no such image")
    engine = create_engine_client(fake_docker)
    assert await engine.inspect_image("missing") is None


def test_create_engine_client_error(monkeypatch) -> None:
    docker_mod = _load_docker_py()
    def mock_from_env():
        raise Exception("Some connection error")
    monkeypatch.setattr(docker_mod, "from_env", mock_from_env)
    with pytest.raises(RuntimeError) as exc_info:
        create_engine_client()
    assert "Docker is not running or cannot be reached" in str(exc_info.value)
    assert "Original error: Some connection error" in str(exc_info.value)
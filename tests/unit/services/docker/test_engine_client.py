"""Parity tests for engine_client — mirrors src/services/docker/engineClient.ts."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.docker.engine_client import _load_docker_py, create_engine_client
from src.services.docker.types import ImageInspect


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
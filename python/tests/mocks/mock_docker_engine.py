"""Mock Docker engine for tool tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from docker_agent.services.docker.types import (
    ContainerInspect,
    ContainerStats,
    ContainerSummary,
    ImageInspect,
    ImageSummary,
)


class MockDockerEngine:
    def __init__(self) -> None:
        self.containers: list[dict[str, Any]] = []
        self.local_images: dict[str, ImageInspect | None] = {}
        self.pull_image_lines: list[str] = []
        self.stats_by_id: dict[str, Any] = {}
        self.inspect_by_id: dict[str, Any] = {}
        self.list_containers_error: BaseException | None = None
        self.pull_image_calls: list[tuple[str, dict[str, Any]]] = []

    async def list_containers(
        self, *, all: bool = False, filters: dict[str, list[str]] | None = None
    ) -> list[ContainerSummary]:
        del all, filters
        if self.list_containers_error is not None:
            raise self.list_containers_error
        return [
            ContainerSummary.model_validate(container)
            for container in self.containers
        ]

    async def inspect(self, container_id: str) -> ContainerInspect:
        explicit = self.inspect_by_id.get(container_id)
        if explicit is not None:
            return ContainerInspect.model_validate(explicit)
        for container in self.containers:
            if container.get("Id") == container_id:
                return ContainerInspect.model_validate(container)
        return ContainerInspect.model_validate({"Id": container_id})

    async def stats(self, container_id: str) -> ContainerStats:
        return ContainerStats.model_validate(
            self.stats_by_id.get(container_id, {})
        )

    async def inspect_image(self, name_or_id: str) -> ImageInspect | None:
        if name_or_id in self.local_images:
            return self.local_images[name_or_id]
        return ImageInspect.model_validate(
            {
                "Id": f"sha256:{name_or_id}",
                "RepoTags": [name_or_id],
                "Size": 1,
                "Architecture": "amd64",
                "Os": "linux",
                "Created": "2026-01-01T00:00:00.000Z",
            }
        )

    async def list_images(
        self, *, filters: dict[str, list[str]] | None = None
    ) -> list[ImageSummary]:
        del filters
        return [
            ImageSummary.model_validate(
                {
                    "Id": image.Id,
                    "RepoTags": image.repo_tags,
                    "Size": image.size,
                    "Created": 0,
                }
            )
            for image in self.local_images.values()
            if image is not None
        ]

    async def pull_image(
        self, image: str, *, signal: Any | None = None
    ) -> AsyncIterator[str]:
        self.pull_image_calls.append((image, {"signal": signal}))
        for line in self.pull_image_lines:
            yield line
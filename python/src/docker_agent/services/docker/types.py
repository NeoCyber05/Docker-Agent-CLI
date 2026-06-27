"""Docker service types and the EngineClient Protocol.

Parity: ``src/services/docker/engineClient.ts:5-130``.

Models are a pydantic v2 translation of the zod schemas in the TS source.
They use ``extra="ignore"`` so docker-py / daemon payloads with extra fields
still parse; only the fields the agent actually reads are typed.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContainerSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    names: list[str] = Field(alias="Names")
    state: str = Field(alias="State")
    labels: dict[str, str] = Field(alias="Labels")


class _ContainerStateHealth(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    status: str = Field(alias="Status")


class _ContainerState(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    status: str = Field(alias="Status")
    health: _ContainerStateHealth | None = Field(default=None, alias="Health")


class _ContainerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    image: str = Field(alias="Image")
    env: list[str] = Field(default_factory=list, alias="Env")
    cmd: list[str] | None = Field(default=None, alias="Cmd")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")


class _ContainerHostConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    binds: list[str] | None = Field(default=None, alias="Binds")
    port_bindings: dict[str, Any] | None = Field(default=None, alias="PortBindings")


class _ContainerNetworkSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    ports: dict[str, list[dict[str, str]] | None] = Field(
        default_factory=dict, alias="Ports"
    )


class ContainerInspect(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    state: _ContainerState = Field(alias="State")
    config: _ContainerConfig = Field(alias="Config")
    host_config: _ContainerHostConfig = Field(alias="HostConfig")
    network_settings: _ContainerNetworkSettings = Field(alias="NetworkSettings")
    restart_count: int = Field(default=0, alias="RestartCount")


class ContainerStats(BaseModel):
    """Minimal passthrough shape; Phase 5 (get_health) reads CPU/memory fields."""

    model_config = ConfigDict(extra="allow")
    cpu_stats: dict[str, Any] | None = None
    precpu_stats: dict[str, Any] | None = None
    memory_stats: dict[str, Any] | None = None


class ImageSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    repo_tags: list[str] = Field(default_factory=list, alias="RepoTags")
    size: int = Field(alias="Size")
    created: int = Field(alias="Created")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_repo_tags(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("RepoTags") is None:
            data = {**data, "RepoTags": []}
        return data


class ImageInspect(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    repo_tags: list[str] = Field(default_factory=list, alias="RepoTags")
    size: int = Field(alias="Size")
    architecture: str = Field(alias="Architecture")
    os: str = Field(alias="Os")
    created: str = Field(alias="Created")


class EngineClient(Protocol):
    """Read-only subset of the Docker engine client used by the agent."""

    async def list_containers(
        self, *, all: bool = False, filters: dict[str, list[str]] | None = None
    ) -> list[ContainerSummary]: ...

    async def inspect(self, container_id: str) -> ContainerInspect: ...

    async def stats(self, container_id: str) -> ContainerStats: ...

    async def inspect_image(self, name_or_id: str) -> ImageInspect | None: ...

    async def list_images(
        self, *, filters: dict[str, list[str]] | None = None
    ) -> list[ImageSummary]: ...

    async def pull_image(
        self, image: str, *, signal: Any | None = None
    ) -> Any: ...


__all__ = [
    "ContainerInspect",
    "ContainerStats",
    "ContainerSummary",
    "EngineClient",
    "ImageInspect",
    "ImageSummary",
]
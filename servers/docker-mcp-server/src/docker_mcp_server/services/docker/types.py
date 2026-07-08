"""
Docker service types and the EngineClient Protocol.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContainerSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    names: list[str] = Field(default_factory=list, alias="Names")
    state: str = Field(default="", alias="State")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_summary_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("Names") is None:
            normalized["Names"] = []
        if normalized.get("Labels") is None:
            normalized["Labels"] = {}
        if normalized.get("State") is None:
            normalized["State"] = ""
        return normalized


class _ContainerStateHealth(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    status: str = Field(alias="Status")


class _ContainerState(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    status: str = Field(default="", alias="Status")
    health: _ContainerStateHealth | None = Field(default=None, alias="Health")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_state_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("Status") is None:
            normalized["Status"] = ""
        return normalized


class _ContainerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    image: str = Field(default="", alias="Image")
    env: list[str] = Field(default_factory=list, alias="Env")
    cmd: list[str] | None = Field(default=None, alias="Cmd")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_config_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("Env") is None:
            normalized["Env"] = []
        if normalized.get("Labels") is None:
            normalized["Labels"] = {}
        if normalized.get("Image") is None:
            normalized["Image"] = ""
        return normalized


class _ContainerHostConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    binds: list[str] | None = Field(default=None, alias="Binds")
    port_bindings: dict[str, Any] | None = Field(default=None, alias="PortBindings")


class _PortBinding(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    host_ip: str = Field(default="", alias="HostIp")
    host_port: str = Field(default="", alias="HostPort")

    @model_validator(mode="before")
    @classmethod
    def _normalize_binding(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        host_port = normalized.get("HostPort")
        if host_port is not None and not isinstance(host_port, str):
            normalized["HostPort"] = str(host_port)
        if normalized.get("HostIp") is None:
            normalized["HostIp"] = ""
        return normalized


class _ContainerNetworkSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    ports: dict[str, list[_PortBinding] | None] = Field(
        default_factory=dict, alias="Ports"
    )


class ContainerInspect(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="Id")
    name: str = Field(default="", alias="Name")
    state: _ContainerState = Field(default_factory=_ContainerState, alias="State")
    config: _ContainerConfig = Field(default_factory=_ContainerConfig, alias="Config")
    host_config: _ContainerHostConfig = Field(
        default_factory=_ContainerHostConfig, alias="HostConfig"
    )
    network_settings: _ContainerNetworkSettings = Field(
        default_factory=_ContainerNetworkSettings, alias="NetworkSettings"
    )
    restart_count: int = Field(default=0, alias="RestartCount")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_inspect_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("Name") is None:
            normalized["Name"] = ""
        if normalized.get("State") is None:
            normalized["State"] = {}
        if normalized.get("Config") is None:
            normalized["Config"] = {}
        if normalized.get("HostConfig") is None:
            normalized["HostConfig"] = {}
        if normalized.get("NetworkSettings") is None:
            normalized["NetworkSettings"] = {}
        return normalized


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

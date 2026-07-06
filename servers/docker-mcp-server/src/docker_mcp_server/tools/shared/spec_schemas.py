"""Stack draft validation schemas.

Parity: ``src/tools/shared/specSchemas.ts``.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from docker_mcp_server.types.stack import ServiceSpec

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)

SERVICE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")

APPROVED_CATALOG_IDS: tuple[str, ...] = (
    "postgresql:16",
    "postgresql:15",
    "redis:7",
    "redis:6",
    "mysql:8.0",
    "mongodb:6.0",
    "nginx:1.27",
)

# Re-export resolved ServiceSpec as DraftServiceSpec for backward compatibility.
DraftServiceSpec = ServiceSpec


class PersistenceSpec(BaseModel):
    model_config = _MODEL_CONFIG
    path: str | None = None
    size: str | None = None


class ConfigMount(BaseModel):
    model_config = _MODEL_CONFIG
    host_path: str = Field(alias="hostPath")
    container_path: str = Field(alias="containerPath")


class NetworkIntent(BaseModel):
    model_config = _MODEL_CONFIG

    name: str
    driver: Literal["bridge", "overlay"] | None = None
    internal: bool | None = None
    external: bool | None = None
    labels: dict[str, str] | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not SERVICE_NAME_PATTERN.match(value):
            raise ValueError(
                "name must match ^[a-z][a-z0-9_-]{0,62}$"
            )
        return value


class VolumeIntent(BaseModel):
    model_config = _MODEL_CONFIG

    name: str
    driver: str | None = None
    driver_opts: dict[str, str] | None = Field(default=None, alias="driverOpts")
    labels: dict[str, str] | None = None
    external: bool | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not SERVICE_NAME_PATTERN.match(value):
            raise ValueError(
                "name must match ^[a-z][a-z0-9_-]{0,62}$"
            )
        return value


class VolumeMount(BaseModel):
    model_config = _MODEL_CONFIG

    volume: str
    target: str
    read_only: bool | None = Field(default=None, alias="readOnly")

    @field_validator("volume")
    @classmethod
    def _validate_volume(cls, value: str) -> str:
        if not SERVICE_NAME_PATTERN.match(value):
            raise ValueError(
                "volume must match ^[a-z][a-z0-9_-]{0,62}$"
            )
        return value


def parse_docker_mount_string(value: str) -> dict[str, str]:
    """Parse Docker short volume syntax into ConfigMount fields."""
    trimmed = value.strip()
    parts = trimmed.rsplit(":", 2)
    if len(parts) == 3 and parts[2] in ("ro", "rw"):
        host, container = parts[0], parts[1]
    elif len(parts) >= 2:
        host, container = parts[0], ":".join(parts[1:])
    else:
        raise ValueError(
            "config mount must be an object with hostPath and containerPath, "
            f"or a Docker volume string 'host:container', got: {value!r}"
        )
    if not host or not container:
        raise ValueError(
            "config mount must be an object with hostPath and containerPath, "
            f"or a Docker volume string 'host:container', got: {value!r}"
        )
    return {"hostPath": host, "containerPath": container}


def format_validation_error(err: ValidationError) -> str:
    parts = []
    for issue in err.errors():
        loc = "/".join(str(x) for x in issue["loc"]) or "<root>"
        parts.append(f"{loc}: {issue['msg']}")
    return "; ".join(parts)


class HybridServiceIntent(BaseModel):
    model_config = _MODEL_CONFIG

    name: str
    kind: Literal["catalog", "custom"]
    catalog_id: str | None = Field(default=None, alias="catalogId")
    image: str | None = None
    command: str | list[str] | None = None
    environment: dict[str, str] | None = None
    exposure: Literal["internal", "public"] | None = None
    container_port: int | None = Field(default=None, alias="containerPort")
    host_port: int | None = Field(default=None, alias="hostPort")
    persistence: PersistenceSpec | None = None
    resources: Literal["small", "medium", "large"] | None = None
    depends_on: list[str] | None = None
    scale: int | None = Field(default=None, ge=1)
    config_mounts: list[ConfigMount] | None = Field(default=None, alias="configMounts")
    networks: list[str] | None = None
    volume_mounts: list[VolumeMount] | None = Field(default=None, alias="volumeMounts")

    @field_validator("config_mounts", mode="before")
    @classmethod
    def _coerce_config_mounts(cls, value: Any) -> Any:
        if value is None:
            return value
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append(parse_docker_mount_string(item))
            else:
                coerced.append(item)
        return coerced

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not SERVICE_NAME_PATTERN.match(value):
            raise ValueError(
                "name must match ^[a-z][a-z0-9_-]{0,62}$"
            )
        return value

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> Self:
        if self.kind == "catalog":
            if not self.catalog_id:
                raise ValueError("catalogId is required when kind is 'catalog'")
            if self.catalog_id not in APPROVED_CATALOG_IDS:
                approved = ", ".join(APPROVED_CATALOG_IDS)
                raise ValueError(
                    f"catalogId '{self.catalog_id}' is not allowed. "
                    f"Approved catalogIds: {approved}"
                )
            if self.image:
                raise ValueError("image cannot be specified for catalog services")
        elif self.kind == "custom":
            if not self.image:
                raise ValueError("image is required when kind is 'custom'")
            if self.catalog_id:
                raise ValueError("catalogId cannot be specified for custom services")
        return self


def validate_services(services: list[HybridServiceIntent]) -> list[HybridServiceIntent]:
    """Validate non-empty, unique service names."""
    if len(services) == 0:
        raise ValueError("at least one service")
    names = [s.name for s in services]
    if len(set(names)) != len(names):
        raise ValueError("service names must be unique")
    return services


class StackDraft(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str = Field(alias="stackName")
    intent: str
    network_name: str | None = Field(default=None, alias="networkName")
    networks: list[NetworkIntent] | None = None
    volumes: list[VolumeIntent] | None = None
    services: list[HybridServiceIntent]
    config_files: dict[str, str] | None = Field(default=None, alias="configFiles")

    @field_validator("stack_name", "network_name")
    @classmethod
    def _validate_stack_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not SERVICE_NAME_PATTERN.match(value):
            raise ValueError(
                "name must match ^[a-z][a-z0-9_-]{0,62}$"
            )
        return value

    @field_validator("services")
    @classmethod
    def _validate_services(
        cls, value: list[HybridServiceIntent]
    ) -> list[HybridServiceIntent]:
        return validate_services(value)

    @model_validator(mode="after")
    def _validate_network_and_volume_references(self) -> Self:
        if self.networks:
            net_names = [n.name for n in self.networks]
            if len(set(net_names)) != len(net_names):
                raise ValueError("network names must be unique")
            if "default" in net_names:
                raise ValueError(
                    "network name 'default' is reserved; use networkName to rename "
                    "the default network"
                )

        if self.volumes:
            vol_names = [v.name for v in self.volumes]
            if len(set(vol_names)) != len(vol_names):
                raise ValueError("volume names must be unique")

        declared_networks = {n.name for n in (self.networks or [])} | {"default"}
        declared_volumes = {v.name for v in (self.volumes or [])}
        for svc in self.services:
            if svc.persistence:
                declared_volumes.add(f"{svc.name}_data")
            if svc.networks:
                for net in svc.networks:
                    if net not in declared_networks:
                        raise ValueError(
                            f"service '{svc.name}' references network '{net}' "
                            "which is not declared in top-level networks"
                        )
            if svc.volume_mounts:
                for mount in svc.volume_mounts:
                    if mount.volume not in declared_volumes:
                        raise ValueError(
                            f"service '{svc.name}' references volume '{mount.volume}' "
                            "which is not declared in top-level volumes"
                        )
        return self


__all__ = [
    "APPROVED_CATALOG_IDS",
    "ConfigMount",
    "DraftServiceSpec",
    "HybridServiceIntent",
    "NetworkIntent",
    "PersistenceSpec",
    "VolumeIntent",
    "VolumeMount",
    "SERVICE_NAME_PATTERN",
    "StackDraft",
    "format_validation_error",
    "parse_docker_mount_string",
    "validate_services",
]

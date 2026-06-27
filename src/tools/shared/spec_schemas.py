"""Stack draft validation schemas.

Parity: ``src/tools/shared/specSchemas.ts``.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.types.stack import ServiceSpec

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


__all__ = [
    "APPROVED_CATALOG_IDS",
    "ConfigMount",
    "DraftServiceSpec",
    "HybridServiceIntent",
    "PersistenceSpec",
    "SERVICE_NAME_PATTERN",
    "StackDraft",
    "validate_services",
]
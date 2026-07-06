"""Stack domain models â€” desired-state YAML schema, drift snapshots, diffs.

Parity: ``src/types/stack.ts:1-97``.

Snake_case python field names with camelCase aliases for TS-shaped payloads.

``ServiceSpec.depends_on`` is a discriminated shape:
either ``list[str]`` (short form) or ``dict[str, {condition: Literal[...]}]``
(long form). We model this as ``Union[list[str], dict[str, DependsOnCondition]]``
without a discriminator because pydantic v2's strict-union fallback dispatches
by shape when both options are mutually exclusive (list vs dict).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)

# --- depends_on condition map --------------------------------------------

DependsOnCondition = dict[str, Literal[
    "service_started", "service_healthy", "service_completed_successfully"
]]


# --- ServiceSpec ----------------------------------------------------------


class HealthcheckSpec(BaseModel):
    """Inline subset of compose's healthcheck block â€” captured here only so
    we can apply the discriminated validation requirements later in Phase 4
    (PolicyEngine uses this shape directly to enforce ``required`` rules)."""

    model_config = _MODEL_CONFIG
    test: str | list[str]
    interval: str | None = None
    timeout: str | None = None
    retries: int | None = None
    start_period: str | None = None


class DeployResourcesLimits(BaseModel):
    model_config = _MODEL_CONFIG
    cpus: str | None = None
    memory: str | None = None


class DeployResources(BaseModel):
    model_config = _MODEL_CONFIG
    limits: DeployResourcesLimits | None = None


class DeploySpec(BaseModel):
    model_config = _MODEL_CONFIG
    resources: DeployResources | None = None


class LoggingSpec(BaseModel):
    model_config = _MODEL_CONFIG
    driver: str | None = None
    options: dict[str, str] | None = None


class ServiceSpec(BaseModel):
    """Per-service compose spec, mirroring ``src/types/stack.ts:1-39``."""

    model_config = _MODEL_CONFIG
    image: str
    command: str | list[str] | None = None
    ports: list[str] | None = None
    environment: dict[str, str] | None = None
    env_file: list[str] | None = None
    volumes: list[str] | None = None
    depends_on: list[str] | dict[str, DependsOnCondition] | None = None
    healthcheck: HealthcheckSpec | None = None
    restart: Literal["no", "always", "on-failure", "unless-stopped"] | None = None
    labels: dict[str, str] | None = None
    networks: list[str] | None = None
    scale: int | None = None
    deploy: DeploySpec | None = None
    logging: LoggingSpec | None = None
    user: str | None = None
    read_only: bool | None = Field(default=None, alias="read_only")


# --- EnvFileSource + DockerAgentMeta --------------------------------------


class EnvFileSource(BaseModel):
    model_config = _MODEL_CONFIG
    generated: bool
    path: str
    added_keys: list[str] | None = Field(default=None, alias="addedKeys")


class DockerAgentMeta(BaseModel):
    """``x-docker-agent:`` metadata block. Aliases preserve the TS camelCase
    field names so YAML round-trips byte-identical through ``StateStore``."""

    model_config = _MODEL_CONFIG
    name: str
    created_at: str = Field(alias="createdAt")
    last_applied: str | None = Field(default=None, alias="lastApplied")
    intent: str
    provider: str
    generated_by: str = Field(alias="generatedBy")
    env_file_sources: dict[str, EnvFileSource] = Field(alias="envFileSources")


class StackDefinition(BaseModel):
    """Full desired-state schema written to ``docker-stacks/<name>.yaml``."""

    model_config = _MODEL_CONFIG

    x_docker_agent: DockerAgentMeta = Field(alias="x-docker-agent")
    services: dict[str, ServiceSpec]
    networks: dict[str, Any] | None = None
    volumes: dict[str, Any] | None = None


# --- StackSummary, ServiceSnapshot, EnvSnapshot --------------------------


class StackSummary(BaseModel):
    model_config = _MODEL_CONFIG
    name: str
    service_count: int = Field(alias="serviceCount")
    last_applied: str | None = Field(default=None, alias="lastApplied")


class EnvSnapshot(BaseModel):
    model_config = _MODEL_CONFIG
    visible: dict[str, str]
    secret_keys: list[str] = Field(alias="secretKeys")
    secret_hashes_by_key: dict[str, str] = Field(alias="secretHashesByKey")


class ServiceSnapshot(BaseModel):
    model_config = _MODEL_CONFIG
    image: str
    command: str | list[str] | None = None
    ports: list[str]
    env: EnvSnapshot
    volumes: list[str]
    replica_count: int = Field(alias="replicaCount")
    state: str | None = None


# --- ServiceDiff, StackDiff ----------------------------------------------


class FieldChange(BaseModel):
    """``{field, from, to}`` row inside ``ServiceDiff.changes``.

    ``from`` and ``to`` are intentionally ``Any`` to mirror TS ``unknown``;
    concrete shape is tool-specific.
    """

    model_config = _MODEL_CONFIG
    field: str
    from_: Any = Field(alias="from")
    to: Any


class ServiceDiff(BaseModel):
    model_config = _MODEL_CONFIG
    service: str
    desired: ServiceSnapshot | None = None
    actual: ServiceSnapshot | None = None
    changes: list[FieldChange]


class StackDiff(BaseModel):
    model_config = _MODEL_CONFIG
    stack_name: str = Field(alias="stackName")
    status: Literal["in_sync", "drift", "missing", "extra"]
    service_diffs: list[ServiceDiff] = Field(alias="serviceDiffs")


__all__ = [
    "DeployResources",
    "DeployResourcesLimits",
    "DeploySpec",
    "DockerAgentMeta",
    "EnvFileSource",
    "EnvSnapshot",
    "FieldChange",
    "HealthcheckSpec",
    "LoggingSpec",
    "ServiceDiff",
    "ServiceSnapshot",
    "ServiceSpec",
    "StackDefinition",
    "StackDiff",
    "StackSummary",
]

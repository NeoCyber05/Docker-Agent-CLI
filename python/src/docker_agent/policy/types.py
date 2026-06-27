"""Policy configuration types.

Parity: ``src/policy/types.ts:1-48``.

Rules that can be either a bare string or a config object are normalized at
parse time into a tagged model with ``rule: Literal[...]`` and optional
``config``. This avoids pydantic v2's strict-union ambiguity while preserving
the YAML/JSON input shape.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResourceLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    cpu_required: bool | None = Field(default=None, alias="cpuRequired")
    memory_required: bool | None = Field(default=None, alias="memoryRequired")
    max_memory: str | None = Field(default=None, alias="maxMemory")


class LoggingRotationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    max_size: str | None = Field(default=None, alias="maxSize")
    max_files: int | None = Field(default=None, alias="maxFiles")


class HealthcheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    required: bool | None = None
    max_interval_seconds: int | None = Field(default=None, alias="maxIntervalSeconds")
    max_timeout_seconds: int | None = Field(default=None, alias="maxTimeoutSeconds")


class UntrustedRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    allowed_registries: list[str] | None = Field(default=None, alias="allowedRegistries")


_DENY_RULE_NAMES = Literal[
    "privileged_containers",
    "mount_docker_socket",
    "mount_host_root",
    "host_pid_namespace",
    "host_network",
    "add_all_linux_capabilities",
    "disable_seccomp",
    "expose_database_publicly",
    "untrusted_registry",
]

_CONFIG_DENY_RULES = frozenset({"untrusted_registry"})


class DenyRule(BaseModel):
    """Normalized deny rule: either a string rule name or untrusted_registry config."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    rule: _DENY_RULE_NAMES
    config: UntrustedRegistryConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        if isinstance(data, str):
            return {"rule": data}
        if isinstance(data, dict):
            if "rule" in data:
                return data
            keys = list(data.keys())
            if len(keys) == 1:
                rule_name = keys[0]
                if rule_name in _CONFIG_DENY_RULES:
                    return {"rule": rule_name, "config": data[rule_name]}
                return {"rule": rule_name}
        raise ValueError("DenyRule must be a string or untrusted_registry object")


_REQUIRE_RULE_NAMES = Literal[
    "resource_limits",
    "logging_rotation",
    "healthcheck",
    "restart_policy",
    "non_root_user",
    "read_only_root_filesystem_when_possible",
    "project_labels",
]

_CONFIG_REQUIRE_RULES = frozenset(
    {"resource_limits", "logging_rotation", "healthcheck"}
)


class RequireRule(BaseModel):
    """Normalized require rule: either a string rule name or a config object."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    rule: _REQUIRE_RULE_NAMES
    config: ResourceLimitsConfig | LoggingRotationConfig | HealthcheckConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        if isinstance(data, str):
            return {"rule": data}
        if isinstance(data, dict):
            if "rule" in data:
                return data
            keys = list(data.keys())
            if len(keys) == 1:
                rule_name = keys[0]
                if rule_name in _CONFIG_REQUIRE_RULES:
                    return {"rule": rule_name, "config": data[rule_name]}
                return {"rule": rule_name}
        raise ValueError("RequireRule must be a string or config object")


class PolicyGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    hard_deny: list[DenyRule] | None = Field(default=None, alias="hardDeny")
    require: list[RequireRule] | None = Field(default=None, alias="require")


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: str | None = Field(default=None, alias="schemaVersion")
    global_group: PolicyGroup | None = Field(default=None, alias="global")
    project_group: PolicyGroup | None = Field(default=None, alias="project")


class PolicyViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    service: str
    rule: str
    message: str
    severity: Literal["deny", "warn"]


__all__ = [
    "DenyRule",
    "HealthcheckConfig",
    "LoggingRotationConfig",
    "PolicyConfig",
    "PolicyGroup",
    "PolicyViolation",
    "RequireRule",
    "ResourceLimitsConfig",
    "UntrustedRegistryConfig",
]
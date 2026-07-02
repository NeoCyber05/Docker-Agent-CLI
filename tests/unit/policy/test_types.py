"""Parity tests for policy types — mirrors src/policy/types.ts."""

import pytest
from pydantic import ValidationError

from docker_agent.policy.types import (
    DenyRule,
    PolicyConfig,
    PolicyViolation,
    RequireRule,
    ResourceLimitsConfig,
)


def test_resource_limits_config() -> None:
    cfg = ResourceLimitsConfig(cpu_required=True, memory_required=True, max_memory="4GiB")
    assert cfg.max_memory == "4GiB"


def test_deny_rule_string_variant() -> None:
    r = DenyRule.model_validate("privileged_containers")
    assert r.rule == "privileged_containers"


def test_deny_rule_untrusted_registry_variant() -> None:
    r = DenyRule.model_validate({"untrusted_registry": {"allowedRegistries": ["docker.io"]}})
    assert r.rule == "untrusted_registry"
    assert r.config is not None
    assert r.config.allowed_registries == ["docker.io"]


def test_require_rule_string_variant() -> None:
    r = RequireRule.model_validate("restart_policy")
    assert r.rule == "restart_policy"


def test_require_rule_resource_limits_variant() -> None:
    r = RequireRule.model_validate({"resource_limits": {"cpuRequired": True}})
    assert r.rule == "resource_limits"
    assert r.config is not None
    assert isinstance(r.config, ResourceLimitsConfig)
    assert r.config.cpu_required is True


def test_require_rule_rejects_advisory_read_only_rule() -> None:
    with pytest.raises(ValidationError):
        RequireRule.model_validate("read_only_root_filesystem_when_possible")


def test_policy_violation_rejects_severity_field() -> None:
    with pytest.raises(ValidationError):
        PolicyViolation.model_validate(
            {
                "service": "web",
                "rule": "restart_policy",
                "message": "A restart policy must be configured",
                "severity": "deny",
            }
        )


def test_policy_config_parses_yaml_shape() -> None:
    cfg = PolicyConfig.model_validate(
        {
            "schemaVersion": "1",
            "global": {
                "hardDeny": ["privileged_containers"],
                "require": ["restart_policy"],
            },
            "project": {
                "hardDeny": [{"untrusted_registry": {"allowedRegistries": []}}],
                "require": [{"healthcheck": {"required": True}}],
            },
        }
    )
    assert cfg.global_group is not None
    assert cfg.global_group.hard_deny is not None
    assert cfg.global_group.hard_deny[0].rule == "privileged_containers"
    assert cfg.project_group is not None
    assert cfg.project_group.hard_deny is not None
    assert cfg.project_group.hard_deny[0].rule == "untrusted_registry"
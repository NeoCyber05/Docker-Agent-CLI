"""Parity tests for policy types â€” mirrors src/policy/types.ts."""

import pytest
from pydantic import ValidationError

from docker_mcp_server.policy.types import (
    DenyRule,
    PidsLimitConfig,
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


@pytest.mark.parametrize(
    "rule_name",
    [
        "wildcard_host_ports",
        "inline_sensitive_env",
        "disable_apparmor",
        "disable_selinux_label",
    ],
)
def test_deny_rule_accepts_new_hard_deny_rules(rule_name: str) -> None:
    r = DenyRule.model_validate(rule_name)
    assert r.rule == rule_name


@pytest.mark.parametrize(
    "rule_name",
    [
        "no_new_privileges",
        "drop_all_capabilities",
        "read_only_root_filesystem",
        "pinned_image_tag",
        "pids_limit",
    ],
)
def test_require_rule_accepts_new_require_rules(rule_name: str) -> None:
    r = RequireRule.model_validate(rule_name)
    assert r.rule == rule_name


def test_require_rule_pids_limit_variant() -> None:
    r = RequireRule.model_validate({"pids_limit": {"required": True, "maxPids": 512}})
    assert r.rule == "pids_limit"
    assert r.config is not None
    assert isinstance(r.config, PidsLimitConfig)
    assert r.config.required is True
    assert r.config.max_pids == 512


def test_require_rule_rejects_unknown_rule() -> None:
    with pytest.raises(ValidationError):
        RequireRule.model_validate("unknown_rule_name")


def test_deny_rule_rejects_unknown_rule() -> None:
    with pytest.raises(ValidationError):
        DenyRule.model_validate("unknown_deny_rule")

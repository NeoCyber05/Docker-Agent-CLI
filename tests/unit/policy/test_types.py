"""Parity tests for policy types — mirrors src/policy/types.ts."""

from src.policy.types import (
    DenyRule,
    PolicyConfig,
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
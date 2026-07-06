"""Tests for default global policy scaffolding."""

from pathlib import Path

import pytest
import yaml

from docker_mcp_server.policy.defaults import (
    DEFAULT_GLOBAL_POLICY_YAML,
    ensure_global_policy,
    global_policy_path,
)
from docker_mcp_server.policy.policy_engine import PolicyEngine
from docker_mcp_server.policy.types import DenyRule, PolicyConfig, RequireRule


def test_global_policy_path_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom = str(tmp_path / "custom-policies.yaml")
    monkeypatch.setenv("DOCKER_AGENT_GLOBAL_POLICY", custom)
    assert global_policy_path() == custom


def test_ensure_global_policy_creates_baseline(tmp_path: Path) -> None:
    target = tmp_path / "policies.yaml"
    assert ensure_global_policy(target) is True
    assert target.exists()
    cfg = PolicyConfig.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")))
    assert cfg.global_group is not None
    assert cfg.global_group.hard_deny is not None
    assert len(cfg.global_group.hard_deny) == 9
    assert cfg.global_group.require is not None
    assert len(cfg.global_group.require) == 3


def test_ensure_global_policy_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "policies.yaml"
    custom = "global:\n  deny: []\n"
    target.write_text(custom, encoding="utf-8")

    assert ensure_global_policy(target) is False
    assert target.read_text(encoding="utf-8") == custom


def test_default_global_policy_yaml_is_valid() -> None:
    cfg = PolicyConfig.model_validate(yaml.safe_load(DEFAULT_GLOBAL_POLICY_YAML))
    assert cfg.global_group is not None
    assert cfg.global_group.hard_deny is not None
    assert "privileged_containers" in {r.rule for r in cfg.global_group.hard_deny}


def test_opt_in_rules_are_valid_but_not_in_default_baseline() -> None:
    cfg = PolicyConfig.model_validate(yaml.safe_load(DEFAULT_GLOBAL_POLICY_YAML))
    assert cfg.global_group is not None
    default_deny = {r.rule for r in cfg.global_group.hard_deny or []}
    default_require = {r.rule for r in cfg.global_group.require or []}

    opt_in_deny = [
        "wildcard_host_ports",
        "inline_sensitive_env",
        "disable_apparmor",
        "disable_selinux_label",
    ]
    opt_in_require = [
        "no_new_privileges",
        "drop_all_capabilities",
        "read_only_root_filesystem",
        "pinned_image_tag",
        "pids_limit",
    ]

    for rule_name in opt_in_deny:
        assert DenyRule.model_validate(rule_name).rule == rule_name
        assert rule_name not in default_deny

    for rule_name in opt_in_require:
        assert RequireRule.model_validate(rule_name).rule == rule_name
        assert rule_name not in default_require


def test_policy_engine_picks_up_scaffolded_global_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PolicyEngine itself has no filesystem side effects (kept test-hermetic);
    scaffolding is an explicit, separate step performed by the CLI bootstrap
    (see query.py / langgraph_backend.py) before constructing the engine.
    """
    global_path = tmp_path / "policies.yaml"
    monkeypatch.setenv("DOCKER_AGENT_GLOBAL_POLICY", str(global_path))
    project_policy = tmp_path / "project-policies.yaml"
    project_policy.write_text("project:\n  deny: []\n  require: []\n", encoding="utf-8")

    assert not global_path.exists()
    engine_before = PolicyEngine(project_policy_path=str(project_policy))
    assert not global_path.exists()
    assert "privileged_containers" not in engine_before.get_effective_policy().hard_deny

    ensure_global_policy()
    engine_after = PolicyEngine(project_policy_path=str(project_policy))
    effective = engine_after.get_effective_policy()

    assert global_path.exists()
    assert "privileged_containers" in effective.hard_deny
    assert "restart_policy" in effective.require


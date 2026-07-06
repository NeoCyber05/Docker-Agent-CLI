"""Parity tests for policy_engine â€” mirrors src/policy/PolicyEngine.ts."""

from pathlib import Path

import pytest

from docker_agent.config import UserConfig
from docker_mcp_server.policy.policy_engine import (
    PolicyEngine,
    parse_duration_to_seconds,
    parse_size_to_bytes,
)
from docker_mcp_server.policy.types import PolicyConfig, PolicyGroup

# --- helper parsing ------------------------------------------------------


def test_parse_size_to_bytes_units() -> None:
    assert parse_size_to_bytes("1024") == 1024
    assert parse_size_to_bytes("1k") == 1024
    assert parse_size_to_bytes("1kb") == 1024
    assert parse_size_to_bytes("1ki") == 1024
    assert parse_size_to_bytes("1kib") == 1024
    assert parse_size_to_bytes("1m") == 1024 * 1024
    assert parse_size_to_bytes("1mb") == 1024 * 1024
    assert parse_size_to_bytes("1g") == 1024 * 1024 * 1024
    assert parse_size_to_bytes("1.5g") == int(1.5 * 1024 * 1024 * 1024)


def test_parse_size_to_bytes_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unknown size unit"):
        parse_size_to_bytes("1x")


def test_parse_duration_to_seconds() -> None:
    assert parse_duration_to_seconds("30") == 30
    assert parse_duration_to_seconds("30s") == 30
    assert parse_duration_to_seconds("2m") == 120
    assert parse_duration_to_seconds("1h") == 3600


# --- construction / loading ----------------------------------------------


def test_policy_engine_loads_global_and_project(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text("global:\n  hardDeny:\n    - privileged_containers\n")
    project_file = tmp_path / "project.yaml"
    project_file.write_text("project:\n  require:\n    - restart_policy\n")
    engine = PolicyEngine(
        global_policy_path=str(global_file),
        project_policy_path=str(project_file),
    )
    effective = engine.get_effective_policy()
    assert "privileged_containers" in effective.hard_deny
    assert "restart_policy" in effective.require


def test_policy_engine_resolves_default_project_policy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    project_policy = "project:\n  hardDeny:\n    - host_network\n"
    (tmp_path / "project-policies.yaml").write_text(project_policy)
    engine = PolicyEngine()
    effective = engine.get_effective_policy()
    assert "host_network" in effective.hard_deny


def test_policy_engine_missing_project_policy_deny_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    engine = PolicyEngine()
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "project_policy_missing" for v in violations)


def test_policy_engine_missing_project_policy_use_global_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = UserConfig(defaults={"missing_project_policy": "use-global"})
    engine = PolicyEngine(user_config=cfg)
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert not any(v.rule == "project_policy_missing" for v in violations)


def test_policy_engine_invalid_yaml_returns_invalid_yaml_violation() -> None:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._global_policy = PolicyGroup()
    engine._project_policy = PolicyGroup()
    engine._has_project_policy = True
    engine._missing_project_policy_mode = "deny"
    violations = engine.evaluate("not: [valid yaml")
    assert any(v.rule == "invalid_yaml" for v in violations)


# --- deny rule coverage --------------------------------------------------


def _engine_with_rule(rule: str) -> PolicyEngine:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._global_policy = PolicyConfig(
        global_group={"hardDeny": [rule], "require": []}
    ).global_group
    engine._project_policy = PolicyConfig(
        project_group={"hardDeny": [], "require": []}
    ).project_group
    engine._has_project_policy = True
    engine._missing_project_policy_mode = "deny"
    return engine


def test_privileged_container_denied() -> None:
    engine = _engine_with_rule("privileged_containers")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n    privileged: true\n")
    assert any(v.rule == "privileged_containers" for v in violations)


def test_docker_socket_mount_denied() -> None:
    engine = _engine_with_rule("mount_docker_socket")
    compose = (
        "services:\n  web:\n    image: nginx\n    volumes:\n"
        "      - /var/run/docker.sock:/var/run/docker.sock\n"
    )
    violations = engine.evaluate(compose)
    assert any(v.rule == "mount_docker_socket" for v in violations)


def test_host_root_mount_denied() -> None:
    engine = _engine_with_rule("mount_host_root")
    violations = engine.evaluate(
        "services:\n  web:\n    image: nginx\n    volumes:\n      - /:/host\n"
    )
    assert any(v.rule == "mount_host_root" for v in violations)


def test_host_pid_namespace_denied() -> None:
    engine = _engine_with_rule("host_pid_namespace")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n    pid: host\n")
    assert any(v.rule == "host_pid_namespace" for v in violations)


def test_host_network_denied() -> None:
    engine = _engine_with_rule("host_network")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n    network_mode: host\n")
    assert any(v.rule == "host_network" for v in violations)


def test_all_capabilities_denied() -> None:
    engine = _engine_with_rule("add_all_linux_capabilities")
    violations = engine.evaluate(
        "services:\n  web:\n    image: nginx\n    cap_add:\n      - ALL\n"
    )
    assert any(v.rule == "add_all_linux_capabilities" for v in violations)


def test_disable_seccomp_denied() -> None:
    engine = _engine_with_rule("disable_seccomp")
    violations = engine.evaluate(
        "services:\n  web:\n    image: nginx\n    security_opt:\n      - seccomp:unconfined\n"
    )
    assert any(v.rule == "disable_seccomp" for v in violations)


def test_untrusted_registry_denied() -> None:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._global_policy = PolicyConfig(
        global_group={"hardDeny": [{"untrusted_registry": {"allowedRegistries": ["docker.io"]}}]}
    ).global_group
    engine._project_policy = PolicyConfig(
        project_group={"hardDeny": [], "require": []}
    ).project_group
    engine._has_project_policy = True
    engine._missing_project_policy_mode = "deny"
    violations = engine.evaluate(
        "services:\n  web:\n    image: my.registry.com/app:latest\n"
    )
    assert any(v.rule == "untrusted_registry" for v in violations)


def test_database_public_port_denied() -> None:
    engine = _engine_with_rule("expose_database_publicly")
    violations = engine.evaluate(
        "services:\n  db:\n    image: postgres:16\n    ports:\n      - 5432:5432\n"
    )
    assert any(v.rule == "expose_database_publicly" for v in violations)


def test_database_localhost_port_allowed() -> None:
    engine = _engine_with_rule("expose_database_publicly")
    violations = engine.evaluate(
        "services:\n  db:\n    image: postgres:16\n    ports:\n      - 127.0.0.1:5432:5432\n"
    )
    assert not any(v.rule == "expose_database_publicly" for v in violations)


# --- require rule coverage -----------------------------------------------


def _engine_with_require(rule: str | dict) -> PolicyEngine:
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._global_policy = PolicyConfig(
        global_group={"hardDeny": [], "require": [rule]}
    ).global_group
    engine._project_policy = PolicyConfig(
        project_group={"hardDeny": [], "require": []}
    ).project_group
    engine._has_project_policy = True
    engine._missing_project_policy_mode = "deny"
    return engine


def test_restart_policy_required() -> None:
    engine = _engine_with_require("restart_policy")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "restart_policy" for v in violations)


def test_resource_limits_required() -> None:
    rule = {"resource_limits": {"cpuRequired": True, "memoryRequired": True}}
    engine = _engine_with_require(rule)
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "resource_limits" and "CPU" in v.message for v in violations)
    assert any(v.rule == "resource_limits" and "Memory" in v.message for v in violations)


def test_logging_rotation_required() -> None:
    engine = _engine_with_require({"logging_rotation": {"maxSize": "10m", "maxFiles": 3}})
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "logging_rotation" for v in violations)


def test_healthcheck_required() -> None:
    engine = _engine_with_require({"healthcheck": {"required": True}})
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "healthcheck" for v in violations)


def test_non_root_user_required() -> None:
    engine = _engine_with_require("non_root_user")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "non_root_user" for v in violations)



def test_project_labels_required() -> None:
    engine = _engine_with_require("project_labels")
    violations = engine.evaluate("services:\n  web:\n    image: nginx\n")
    assert any(v.rule == "project_labels" for v in violations)


# --- hierarchy validation ------------------------------------------------


def test_project_cannot_loosen_cpu_required(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text(
        "global:\n  require:\n    - resource_limits:\n        cpuRequired: true\n"
    )
    project_file = tmp_path / "project.yaml"
    project_file.write_text(
        "project:\n  require:\n    - resource_limits:\n        cpuRequired: false\n"
    )
    with pytest.raises(ValueError, match="cannot disable cpuRequired"):
        PolicyEngine(global_policy_path=str(global_file), project_policy_path=str(project_file))


def test_project_cannot_exceed_global_max_memory(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text("global:\n  require:\n    - resource_limits:\n        maxMemory: 1g\n")
    project_file = tmp_path / "project.yaml"
    project_file.write_text("project:\n  require:\n    - resource_limits:\n        maxMemory: 2g\n")
    with pytest.raises(ValueError, match="cannot exceed Global maxMemory"):
        PolicyEngine(global_policy_path=str(global_file), project_policy_path=str(project_file))


def test_project_registry_whitelist_subset_of_global(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text(
        "global:\n  hardDeny:\n    - untrusted_registry:\n"
        "        allowedRegistries:\n          - docker.io\n"
    )
    project_file = tmp_path / "project.yaml"
    project_file.write_text(
        "project:\n  hardDeny:\n    - untrusted_registry:\n"
        "        allowedRegistries:\n          - my.registry.com\n"
    )
    with pytest.raises(ValueError, match="not in Global registry whitelist"):
        PolicyEngine(global_policy_path=str(global_file), project_policy_path=str(project_file))


# --- new hardDeny rules --------------------------------------------------


@pytest.mark.parametrize(
    "compose",
    [
        "services:\n  web:\n    image: nginx:1.27\n    ports:\n      - 8080:80\n",
        "services:\n  web:\n    image: nginx:1.27\n    ports:\n      - 0.0.0.0:8080:80\n",
        (
            "services:\n  web:\n    image: nginx:1.27\n    ports:\n"
            "      - published: 8080\n        target: 80\n"
        ),
    ],
)
def test_wildcard_host_ports_denied(compose: str) -> None:
    engine = _engine_with_rule("wildcard_host_ports")
    violations = engine.evaluate(compose)
    assert any(v.rule == "wildcard_host_ports" for v in violations)


@pytest.mark.parametrize(
    "compose",
    [
        "services:\n  web:\n    image: nginx:1.27\n    ports:\n      - 127.0.0.1:8080:80\n",
        "services:\n  web:\n    image: nginx:1.27\n    ports:\n      - localhost:8080:80\n",
        (
            "services:\n  web:\n    image: nginx:1.27\n    ports:\n"
            "      - published: 8080\n        target: 80\n        host_ip: 127.0.0.1\n"
        ),
    ],
)
def test_wildcard_host_ports_allows_localhost(compose: str) -> None:
    engine = _engine_with_rule("wildcard_host_ports")
    violations = engine.evaluate(compose)
    assert not any(v.rule == "wildcard_host_ports" for v in violations)


def test_inline_sensitive_env_denies_literal_values() -> None:
    engine = _engine_with_rule("inline_sensitive_env")
    compose_dict = (
        "services:\n  db:\n    image: postgres:16\n    environment:\n"
        "      POSTGRES_PASSWORD: plain-text\n"
    )
    compose_list = (
        "services:\n  api:\n    image: nginx:1.27\n    environment:\n"
        "      - API_KEY=plain-text\n"
    )
    assert any(
        v.rule == "inline_sensitive_env"
        for v in engine.evaluate(compose_dict)
    )
    assert any(
        v.rule == "inline_sensitive_env"
        for v in engine.evaluate(compose_list)
    )


def test_inline_sensitive_env_allows_file_and_interpolation() -> None:
    engine = _engine_with_rule("inline_sensitive_env")
    compose = (
        "services:\n  db:\n    image: postgres:16\n    environment:\n"
        "      POSTGRES_PASSWORD_FILE: /run/secrets/db_password\n"
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"
    )
    violations = engine.evaluate(compose)
    assert not any(v.rule == "inline_sensitive_env" for v in violations)


def test_disable_apparmor_denied() -> None:
    engine = _engine_with_rule("disable_apparmor")
    violations = engine.evaluate(
        "services:\n  web:\n    image: nginx:1.27\n    security_opt:\n"
        "      - apparmor:unconfined\n"
    )
    assert any(v.rule == "disable_apparmor" for v in violations)


def test_disable_selinux_label_denied() -> None:
    engine = _engine_with_rule("disable_selinux_label")
    violations = engine.evaluate(
        "services:\n  web:\n    image: nginx:1.27\n    security_opt:\n      - label:disable\n"
    )
    assert any(v.rule == "disable_selinux_label" for v in violations)


# --- new require rules ---------------------------------------------------


def test_no_new_privileges_required() -> None:
    engine = _engine_with_require("no_new_privileges")
    violations = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n")
    assert any(v.rule == "no_new_privileges" for v in violations)

    ok = engine.evaluate(
        "services:\n  web:\n    image: nginx:1.27\n    security_opt:\n"
        "      - no-new-privileges:true\n"
    )
    assert not any(v.rule == "no_new_privileges" for v in ok)


def test_drop_all_capabilities_required() -> None:
    engine = _engine_with_require("drop_all_capabilities")
    violations = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n")
    assert any(v.rule == "drop_all_capabilities" for v in violations)

    ok = engine.evaluate(
        "services:\n  web:\n    image: nginx:1.27\n    cap_drop:\n      - ALL\n"
    )
    assert not any(v.rule == "drop_all_capabilities" for v in ok)


def test_read_only_root_filesystem_required() -> None:
    engine = _engine_with_require("read_only_root_filesystem")
    violations = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n")
    assert any(v.rule == "read_only_root_filesystem" for v in violations)

    ok = engine.evaluate(
        "services:\n  web:\n    image: nginx:1.27\n    read_only: true\n"
    )
    assert not any(v.rule == "read_only_root_filesystem" for v in ok)


@pytest.mark.parametrize(
    "image",
    ["nginx", "nginx:latest"],
)
def test_pinned_image_tag_denies_unpinned(image: str) -> None:
    engine = _engine_with_require("pinned_image_tag")
    violations = engine.evaluate(f"services:\n  web:\n    image: {image}\n")
    assert any(v.rule == "pinned_image_tag" for v in violations)


@pytest.mark.parametrize(
    "image",
    ["nginx:1.27-alpine", "nginx@sha256:abc123"],
)
def test_pinned_image_tag_allows_pinned(image: str) -> None:
    engine = _engine_with_require("pinned_image_tag")
    violations = engine.evaluate(f"services:\n  web:\n    image: {image}\n")
    assert not any(v.rule == "pinned_image_tag" for v in violations)


def test_pids_limit_required_and_max() -> None:
    rule = {"pids_limit": {"required": True, "maxPids": 512}}
    engine = _engine_with_require(rule)
    missing = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n")
    assert any(v.rule == "pids_limit" and "required" in v.message.lower() for v in missing)

    too_high = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n    pids_limit: 1024\n")
    assert any(v.rule == "pids_limit" and "exceeds" in v.message.lower() for v in too_high)

    ok = engine.evaluate("services:\n  web:\n    image: nginx:1.27\n    pids_limit: 256\n")
    assert not any(v.rule == "pids_limit" for v in ok)


def test_project_cannot_loosen_pids_limit_required(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text(
        "global:\n  require:\n    - pids_limit:\n        required: true\n        maxPids: 512\n"
    )
    project_file = tmp_path / "project.yaml"
    project_file.write_text(
        "project:\n  require:\n    - pids_limit:\n        required: false\n        maxPids: 256\n"
    )
    with pytest.raises(ValueError, match="cannot disable pids_limit required"):
        PolicyEngine(global_policy_path=str(global_file), project_policy_path=str(project_file))


def test_project_cannot_exceed_global_max_pids(tmp_path: Path) -> None:
    global_file = tmp_path / "global.yaml"
    global_file.write_text(
        "global:\n  require:\n    - pids_limit:\n        required: true\n        maxPids: 512\n"
    )
    project_file = tmp_path / "project.yaml"
    project_file.write_text(
        "project:\n  require:\n    - pids_limit:\n        required: true\n        maxPids: 1024\n"
    )
    with pytest.raises(ValueError, match="cannot exceed Global maxPids"):
        PolicyEngine(global_policy_path=str(global_file), project_policy_path=str(project_file))

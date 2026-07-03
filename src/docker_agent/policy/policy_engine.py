"""Policy engine: load, validate, and evaluate Compose deployments.

Parity: ``src/policy/PolicyEngine.ts``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml

from docker_agent.config import UserConfig
from docker_agent.policy.defaults import global_policy_path as default_global_policy_path
from docker_agent.policy.types import (
    DenyRule,
    HealthcheckConfig,
    LoggingRotationConfig,
    PidsLimitConfig,
    PolicyConfig,
    PolicyGroup,
    PolicyViolation,
    RequireRule,
    ResourceLimitsConfig,
    UntrustedRegistryConfig,
)


def parse_size_to_bytes(size_str: str) -> float:
    """Parse a human-readable size string into bytes."""
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$", size_str.strip())
    if not match:
        raise ValueError(f"Invalid size format: {size_str}")
    value = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "": 1,
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "ki": 1024,
        "kib": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "mi": 1024**2,
        "mib": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "gi": 1024**3,
        "gib": 1024**3,
    }
    if unit not in multipliers:
        raise ValueError(f"Unknown size unit: {unit}")
    return value * multipliers[unit]


def _is_kubernetes_memory_unit(memory: str) -> bool:
    """Return True when memory uses Kubernetes-style binary suffix (Ki/Mi/Gi/Ti)."""
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", memory.strip())
    if not match:
        return False
    unit = match.group(2)
    return bool(re.fullmatch(r"[KMGTP]i(B)?", unit, re.IGNORECASE))


def parse_duration_to_seconds(duration_str: str) -> float:
    """Parse a duration string (e.g. '10s', '2m', '1h') into seconds."""
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(s|m|h)?$", duration_str.strip())
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")
    value = float(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {"s": 1, "m": 60, "h": 3600}
    return value * multipliers.get(unit, 1)


_LOCALHOST_HOST_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})
_WILDCARD_HOST_BINDS = frozenset({"0.0.0.0", "::", ""})
_SENSITIVE_ENV_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api-key",
    "api_key",
    "access-key",
    "access_key",
    "private-key",
    "private_key",
)


def _normalize_security_opt(opt: str) -> str:
    return opt.lower().replace(" ", "")


def _is_localhost_host_bind(host_ip: str | None) -> bool:
    if host_ip is None:
        return False
    return host_ip.strip().lower() in _LOCALHOST_HOST_BINDS


def _is_wildcard_host_port(port: str | dict[str, Any]) -> bool:
    if isinstance(port, dict):
        host_ip = port.get("host_ip")
        if host_ip is None:
            return True
        host_ip_str = str(host_ip).strip()
        if host_ip_str.lower() in _WILDCARD_HOST_BINDS:
            return True
        return not _is_localhost_host_bind(host_ip_str)

    port_str = port.split("/")[0]
    if port_str.startswith("[") and "]:" in port_str:
        host_part, _, _ = port_str.partition("]:")
        host_ip = host_part.lstrip("[")
        return not _is_localhost_host_bind(host_ip)

    parts = port_str.split(":")
    if len(parts) == 2:
        return True
    if len(parts) >= 3:
        host_ip = parts[0]
        if host_ip.lower() in _WILDCARD_HOST_BINDS:
            return True
        return not _is_localhost_host_bind(host_ip)
    return True


def _is_sensitive_env_key(key: str) -> bool:
    if key.endswith("_FILE"):
        return False
    normalized = key.lower().replace("_", "-")
    return any(part in normalized for part in _SENSITIVE_ENV_KEY_PARTS)


def _is_interpolated_env_value(value: str) -> bool:
    return "${" in value


def _iter_env_entries(
    environment: list[str] | dict[str, str] | None,
) -> list[tuple[str, str]]:
    if not environment:
        return []
    if isinstance(environment, dict):
        return [(str(key), str(val)) for key, val in environment.items()]
    entries: list[tuple[str, str]] = []
    for item in environment:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, _, value = item.partition("=")
        entries.append((key, value))
    return entries


def _has_no_new_privileges(security_opt: list[str]) -> bool:
    for opt in security_opt:
        normalized = _normalize_security_opt(opt)
        if normalized in {"no-new-privileges:true", "no-new-privileges=true"}:
            return True
    return False


def _has_pinned_image_tag(image: str) -> bool:
    if "@" in image:
        return True
    if ":" not in image:
        return False
    tag = image.rsplit(":", 1)[-1]
    return tag.lower() != "latest"


def _find_require_config(
    group: PolicyGroup, rule_name: str
) -> ResourceLimitsConfig | LoggingRotationConfig | HealthcheckConfig | PidsLimitConfig | None:
    if not group.require:
        return None
    for rule in group.require:
        if rule.rule == rule_name and rule.config is not None:
            return rule.config
    return None


def _find_deny_config(
    group: PolicyGroup, rule_name: str
) -> UntrustedRegistryConfig | None:
    if not group.hard_deny:
        return None
    for rule in group.hard_deny:
        if rule.rule == rule_name and rule.config is not None:
            return rule.config
    return None


class PolicyEngine:
    """Loads global + project policies and evaluates Compose YAML."""

    def __init__(
        self,
        *,
        global_policy_path: str | None = None,
        project_policy_path: str | None = None,
        user_config: UserConfig | None = None,
    ) -> None:
        self._global_policy: PolicyGroup = PolicyGroup()
        self._project_policy: PolicyGroup = PolicyGroup()
        self._has_project_policy = False
        self._missing_project_policy_mode: Literal["use-global", "deny"] = "deny"

        if global_policy_path is None:
            global_policy_path = default_global_policy_path()

        if project_policy_path is None:
            project_policy_path = str(Path(os.getcwd()) / "project-policies.yaml")

        self._missing_project_policy_mode = (
            user_config.defaults.missing_project_policy
            if user_config is not None
            else "deny"
        )

        self._load_policies(global_policy_path, project_policy_path)

    def _load_policies(self, global_path: str, project_path: str) -> None:
        if Path(global_path).exists():
            try:
                raw = yaml.safe_load(Path(global_path).read_text(encoding="utf-8"))
                cfg = PolicyConfig.model_validate(raw or {})
                if cfg.global_group:
                    self._global_policy = cfg.global_group
            except Exception as err:
                raise ValueError(f"Failed to parse global policy file: {err}") from err

        if Path(project_path).exists():
            try:
                raw = yaml.safe_load(Path(project_path).read_text(encoding="utf-8"))
                cfg = PolicyConfig.model_validate(raw or {})
                if cfg.project_group:
                    self._project_policy = cfg.project_group
                    self._has_project_policy = True
            except Exception as err:
                raise ValueError(f"Failed to parse project policy file: {err}") from err
        else:
            self._has_project_policy = False

        self._validate_policy_hierarchy()

    def _validate_policy_hierarchy(self) -> None:
        if not self._has_project_policy:
            return

        global_limits = _find_require_config(self._global_policy, "resource_limits")
        project_limits = _find_require_config(self._project_policy, "resource_limits")
        if isinstance(global_limits, ResourceLimitsConfig) and isinstance(
            project_limits, ResourceLimitsConfig
        ):
            if global_limits.cpu_required and project_limits.cpu_required is False:
                raise ValueError(
                    "Invalid policy configuration: Project policy cannot disable "
                    "cpuRequired if enabled globally"
                )
            if global_limits.memory_required and project_limits.memory_required is False:
                raise ValueError(
                    "Invalid policy configuration: Project policy cannot disable "
                    "memoryRequired if enabled globally"
                )
            if (
                global_limits.max_memory
                and project_limits.max_memory
                and parse_size_to_bytes(project_limits.max_memory)
                > parse_size_to_bytes(global_limits.max_memory)
            ):
                raise ValueError(
                    "Invalid policy configuration: Project maxMemory "
                    f"({project_limits.max_memory}) cannot exceed Global maxMemory "
                    f"({global_limits.max_memory})"
                )

        global_log = _find_require_config(self._global_policy, "logging_rotation")
        project_log = _find_require_config(self._project_policy, "logging_rotation")
        if isinstance(global_log, LoggingRotationConfig) and isinstance(
            project_log, LoggingRotationConfig
        ):
            if (
                global_log.max_size
                and project_log.max_size
                and parse_size_to_bytes(project_log.max_size)
                > parse_size_to_bytes(global_log.max_size)
            ):
                raise ValueError(
                    "Invalid policy configuration: Project maxSize "
                    f"({project_log.max_size}) cannot exceed Global maxSize "
                    f"({global_log.max_size})"
                )
            if (
                global_log.max_files is not None
                and project_log.max_files is not None
                and project_log.max_files > global_log.max_files
            ):
                raise ValueError(
                    f"Invalid policy configuration: Project maxFiles ({project_log.max_files}) "
                    f"cannot exceed Global maxFiles ({global_log.max_files})"
                )

        global_health = _find_require_config(self._global_policy, "healthcheck")
        project_health = _find_require_config(self._project_policy, "healthcheck")
        if isinstance(global_health, HealthcheckConfig) and isinstance(
            project_health, HealthcheckConfig
        ):
            if global_health.required and project_health.required is False:
                raise ValueError(
                    "Invalid policy configuration: Project policy cannot disable "
                    "healthcheck required if enabled globally"
                )
            if (
                global_health.max_interval_seconds is not None
                and project_health.max_interval_seconds is not None
                and project_health.max_interval_seconds > global_health.max_interval_seconds
            ):
                raise ValueError(
                    "Invalid policy configuration: Project maxIntervalSeconds "
                    f"({project_health.max_interval_seconds}) cannot exceed Global "
                    f"maxIntervalSeconds ({global_health.max_interval_seconds})"
                )
            if (
                global_health.max_timeout_seconds is not None
                and project_health.max_timeout_seconds is not None
                and project_health.max_timeout_seconds > global_health.max_timeout_seconds
            ):
                raise ValueError(
                    "Invalid policy configuration: Project maxTimeoutSeconds "
                    f"({project_health.max_timeout_seconds}) cannot exceed Global "
                    f"maxTimeoutSeconds ({global_health.max_timeout_seconds})"
                )

        global_reg = _find_deny_config(self._global_policy, "untrusted_registry")
        project_reg = _find_deny_config(self._project_policy, "untrusted_registry")
        if (
            global_reg
            and project_reg
            and global_reg.allowed_registries
            and project_reg.allowed_registries
        ):
            global_set = set(global_reg.allowed_registries)
            for reg in project_reg.allowed_registries:
                if reg not in global_set:
                    raise ValueError(
                        "Invalid policy configuration: Project registry whitelist "
                        f"allows registry '{reg}' which is not in Global registry whitelist"
                    )

        global_pids = _find_require_config(self._global_policy, "pids_limit")
        project_pids = _find_require_config(self._project_policy, "pids_limit")
        if isinstance(global_pids, PidsLimitConfig) and isinstance(project_pids, PidsLimitConfig):
            if global_pids.required and project_pids.required is False:
                raise ValueError(
                    "Invalid policy configuration: Project policy cannot disable "
                    "pids_limit required if enabled globally"
                )
            if (
                global_pids.max_pids is not None
                and project_pids.max_pids is not None
                and project_pids.max_pids > global_pids.max_pids
            ):
                raise ValueError(
                    "Invalid policy configuration: Project maxPids "
                    f"({project_pids.max_pids}) cannot exceed Global maxPids "
                    f"({global_pids.max_pids})"
                )

    def get_effective_policy(self) -> Any:
        """Return merged effective policy as a simple object."""
        hard_deny: set[str] = set()
        require: set[str] = set()
        untrusted_registry: UntrustedRegistryConfig | None = None
        resource_limits: ResourceLimitsConfig | None = None
        logging_rotation: LoggingRotationConfig | None = None
        healthcheck: HealthcheckConfig | None = None
        pids_limit: PidsLimitConfig | None = None

        def process_deny(rule: DenyRule) -> None:
            nonlocal untrusted_registry
            hard_deny.add(rule.rule)
            if rule.rule == "untrusted_registry" and rule.config is not None:
                global_reg = _find_deny_config(self._global_policy, "untrusted_registry")
                if rule.config and global_reg:
                    untrusted_registry = rule.config
                else:
                    untrusted_registry = rule.config or global_reg

        def process_require(rule: RequireRule) -> None:
            nonlocal resource_limits, logging_rotation, healthcheck, pids_limit
            require.add(rule.rule)
            if rule.rule == "resource_limits" and isinstance(rule.config, ResourceLimitsConfig):
                global_limits = _find_require_config(self._global_policy, "resource_limits")
                if isinstance(global_limits, ResourceLimitsConfig):
                    resource_limits = ResourceLimitsConfig.model_validate(
                        {
                            "cpu_required": global_limits.cpu_required
                            or rule.config.cpu_required,
                            "memory_required": global_limits.memory_required
                            or rule.config.memory_required,
                            "max_memory": rule.config.max_memory
                            or global_limits.max_memory,
                        }
                    )
                else:
                    resource_limits = rule.config
            elif rule.rule == "logging_rotation" and isinstance(rule.config, LoggingRotationConfig):
                global_log = _find_require_config(self._global_policy, "logging_rotation")
                if isinstance(global_log, LoggingRotationConfig):
                    logging_rotation = LoggingRotationConfig.model_validate(
                        {
                            "max_size": rule.config.max_size or global_log.max_size,
                            "max_files": rule.config.max_files
                            if rule.config.max_files is not None
                            else global_log.max_files,
                        }
                    )
                else:
                    logging_rotation = rule.config
            elif rule.rule == "healthcheck" and isinstance(rule.config, HealthcheckConfig):
                global_health = _find_require_config(self._global_policy, "healthcheck")
                if isinstance(global_health, HealthcheckConfig):
                    healthcheck = HealthcheckConfig.model_validate(
                        {
                            "required": global_health.required or rule.config.required,
                            "max_interval_seconds": rule.config.max_interval_seconds
                            if rule.config.max_interval_seconds is not None
                            else global_health.max_interval_seconds,
                            "max_timeout_seconds": rule.config.max_timeout_seconds
                            if rule.config.max_timeout_seconds is not None
                            else global_health.max_timeout_seconds,
                        }
                    )
                else:
                    healthcheck = rule.config
            elif rule.rule == "pids_limit" and isinstance(rule.config, PidsLimitConfig):
                global_pids = _find_require_config(self._global_policy, "pids_limit")
                if isinstance(global_pids, PidsLimitConfig):
                    pids_limit = PidsLimitConfig.model_validate(
                        {
                            "required": global_pids.required or rule.config.required,
                            "max_pids": rule.config.max_pids
                            if rule.config.max_pids is not None
                            else global_pids.max_pids,
                        }
                    )
                else:
                    pids_limit = rule.config

        for deny_rule in self._global_policy.hard_deny or []:
            process_deny(deny_rule)
        for require_rule in self._global_policy.require or []:
            process_require(require_rule)
        for deny_rule in self._project_policy.hard_deny or []:
            process_deny(deny_rule)
        for require_rule in self._project_policy.require or []:
            process_require(require_rule)

        class _EffectivePolicy:
            def __init__(self) -> None:
                self.hard_deny = hard_deny
                self.require = require
                self.untrusted_registry = untrusted_registry
                self.resource_limits = resource_limits
                self.logging_rotation = logging_rotation
                self.healthcheck = healthcheck
                self.pids_limit = pids_limit

        return _EffectivePolicy()

    def evaluate(self, compose_yaml: str) -> list[PolicyViolation]:
        """Evaluate Compose YAML against effective policy."""
        violations: list[PolicyViolation] = []

        if (
            not self._has_project_policy
            and self._missing_project_policy_mode == "deny"
        ):
            violations.append(
                PolicyViolation(
                    service="*",
                    rule="project_policy_missing",
                    message="Project policy not found. Deployment is denied.",
                )
            )
            return violations

        try:
            doc = yaml.safe_load(compose_yaml)
        except Exception as err:
            violations.append(
                PolicyViolation(
                    service="*",
                    rule="invalid_yaml",
                    message=f"Failed to parse Compose YAML: {err}",
                )
            )
            return violations

        if not isinstance(doc, dict) or not doc.get("services"):
            return violations

        effective = self.get_effective_policy()
        services = doc.get("services", {})
        if not isinstance(services, dict):
            return violations

        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            self._evaluate_service(name, svc, effective, violations)

        return violations

    def _evaluate_service(
        self, name: str, svc: dict[str, Any], effective: Any, violations: list[PolicyViolation]
    ) -> None:
        if "privileged_containers" in effective.hard_deny and svc.get("privileged") is True:
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="privileged_containers",
                    message="Privileged container is not allowed",
                )
            )

        if "mount_docker_socket" in effective.hard_deny:
            for vol in svc.get("volumes", []) or []:
                host_path = vol.split(":")[0] if isinstance(vol, str) else vol.get("source")
                if host_path == "/var/run/docker.sock":
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="mount_docker_socket",
                            message="Mounting docker socket (/var/run/docker.sock) is not allowed",
                        )
                    )

        if "mount_host_root" in effective.hard_deny:
            forbidden = {"/", "/etc", "/root", "/usr", "/var"}
            for vol in svc.get("volumes", []) or []:
                host_path = vol.split(":")[0] if isinstance(vol, str) else vol.get("source")
                if host_path and os.path.normpath(host_path).replace("\\", "/") in forbidden:
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="mount_host_root",
                            message=(
                                f"Mounting host root or system directory ({host_path}) "
                                "is not allowed"
                            ),
                        )
                    )

        if "host_pid_namespace" in effective.hard_deny and svc.get("pid") == "host":
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="host_pid_namespace",
                    message="Host PID namespace configuration is not allowed",
                )
            )

        if "host_network" in effective.hard_deny and svc.get("network_mode") == "host":
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="host_network",
                    message="Host network mode is not allowed",
                )
            )

        if "add_all_linux_capabilities" in effective.hard_deny:
            cap_add = svc.get("cap_add", []) or []
            if "ALL" in cap_add or "all" in cap_add:
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="add_all_linux_capabilities",
                        message="Adding ALL Linux capabilities is not allowed",
                    )
                )

        if "disable_seccomp" in effective.hard_deny:
            for opt in svc.get("security_opt", []) or []:
                if opt.lower().replace(" ", "") == "seccomp:unconfined":
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="disable_seccomp",
                            message="Disabling seccomp (seccomp:unconfined) is not allowed",
                        )
                    )

        if "untrusted_registry" in effective.hard_deny and effective.untrusted_registry:
            image = svc.get("image", "")
            allowed = effective.untrusted_registry.allowed_registries or []
            registry = self._extract_registry(image)
            if registry not in allowed:
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="untrusted_registry",
                        message=(
                            f"Image uses untrusted registry '{registry}'. "
                            f"Allowed registries: {', '.join(allowed)}"
                        ),
                    )
                )

        if "expose_database_publicly" in effective.hard_deny:
            image = svc.get("image", "")
            if self._is_database_image(image):
                for port in svc.get("ports", []) or []:
                    if isinstance(port, str):
                        port_str = port
                    else:
                        port_str = f"{port.get('published')}:{port.get('target')}"
                    is_local = port_str.startswith("127.0.0.1:") or port_str.startswith(
                        "localhost:"
                    )
                    if not is_local:
                        violations.append(
                            PolicyViolation(
                                service=name,
                                rule="expose_database_publicly",
                                message=(
                                    f"Exposing database port ({port_str}) publicly is not "
                                    "allowed. Expose it to 127.0.0.1 or keep it within the "
                                    "container network."
                                ),
                            )
                        )

        if "wildcard_host_ports" in effective.hard_deny:
            for port in svc.get("ports", []) or []:
                if _is_wildcard_host_port(port):
                    port_display = port if isinstance(port, str) else str(port)
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="wildcard_host_ports",
                            message=(
                                f"Published port ({port_display}) must bind to localhost "
                                "(127.0.0.1, localhost, or ::1), not all interfaces"
                            ),
                        )
                    )

        if "inline_sensitive_env" in effective.hard_deny:
            for key, value in _iter_env_entries(svc.get("environment")):
                if not _is_sensitive_env_key(key):
                    continue
                if _is_interpolated_env_value(value):
                    continue
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="inline_sensitive_env",
                        message=(
                            f"Sensitive environment variable '{key}' must not contain "
                            "a literal value; use *_FILE or ${...} interpolation"
                        ),
                    )
                )

        if "disable_apparmor" in effective.hard_deny:
            for opt in svc.get("security_opt", []) or []:
                if _normalize_security_opt(str(opt)) == "apparmor:unconfined":
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="disable_apparmor",
                            message="Disabling AppArmor (apparmor:unconfined) is not allowed",
                        )
                    )

        if "disable_selinux_label" in effective.hard_deny:
            for opt in svc.get("security_opt", []) or []:
                if _normalize_security_opt(str(opt)) == "label:disable":
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="disable_selinux_label",
                            message="Disabling SELinux label (label:disable) is not allowed",
                        )
                    )

        if "restart_policy" in effective.require:
            restart = svc.get("restart")
            if not restart or restart == "no":
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="restart_policy",
                        message="A restart policy (other than 'no') must be configured",
                    )
                )

        if "resource_limits" in effective.require and effective.resource_limits:
            limits = (svc.get("deploy") or {}).get("resources", {}).get("limits", {})
            conf = effective.resource_limits
            if conf.cpu_required and not limits.get("cpus"):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="resource_limits",
                        message="CPU limits are required",
                    )
                )
            if conf.memory_required and not limits.get("memory"):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="resource_limits",
                        message="Memory limits are required",
                    )
                )
            memory_limit = limits.get("memory")
            if isinstance(memory_limit, str) and _is_kubernetes_memory_unit(memory_limit):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="resource_limits",
                        message=(
                            f"Memory limit ({memory_limit}) uses Kubernetes-style unit; "
                            "Docker Compose requires b/k/m/g without 'i' suffix (e.g. 1g, 512m)"
                        ),
                    )
                )
            if (
                conf.max_memory
                and limits.get("memory")
                and parse_size_to_bytes(limits["memory"])
                > parse_size_to_bytes(conf.max_memory)
            ):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="resource_limits",
                        message=(
                            f"Memory limit ({limits['memory']}) exceeds maximum allowed "
                            f"limit ({conf.max_memory})"
                        ),
                    )
                )

        if "logging_rotation" in effective.require and effective.logging_rotation:
            log_config = svc.get("logging") or {}
            conf = effective.logging_rotation
            if not log_config or log_config.get("driver") != "json-file":
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="logging_rotation",
                        message="Logging driver 'json-file' must be configured for log rotation",
                    )
                )
            else:
                options = log_config.get("options") or {}
                max_size = options.get("max-size")
                max_files = options.get("max-file")
                max_size_exceeded = conf.max_size and (
                    not max_size
                    or parse_size_to_bytes(max_size) > parse_size_to_bytes(conf.max_size)
                )
                if max_size_exceeded:
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="logging_rotation",
                            message=(
                                f"Log max-size ({max_size or 'unlimited'}) is missing or "
                                f"exceeds allowed size ({conf.max_size})"
                            ),
                        )
                    )
                max_files_exceeded = conf.max_files is not None and (
                    not max_files or int(max_files) > conf.max_files
                )
                if max_files_exceeded:
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="logging_rotation",
                            message=(
                                f"Log max-file ({max_files or 'unlimited'}) is missing or "
                                f"exceeds allowed files ({conf.max_files})"
                            ),
                        )
                    )

        if "healthcheck" in effective.require and effective.healthcheck:
            hc = svc.get("healthcheck") or {}
            conf = effective.healthcheck
            if conf.required and (not hc or not hc.get("test") or hc.get("disable") is True):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="healthcheck",
                        message="Healthcheck is required",
                    )
                )
            elif hc and hc.get("disable") is not True:
                interval = hc.get("interval")
                if (
                    conf.max_interval_seconds is not None
                    and interval
                    and parse_duration_to_seconds(interval) > conf.max_interval_seconds
                ):
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="healthcheck",
                            message=(
                                f"Healthcheck interval ({interval}) exceeds maximum interval "
                                f"({conf.max_interval_seconds}s)"
                            ),
                        )
                    )
                timeout = hc.get("timeout")
                if (
                    conf.max_timeout_seconds is not None
                    and timeout
                    and parse_duration_to_seconds(timeout) > conf.max_timeout_seconds
                ):
                    violations.append(
                        PolicyViolation(
                            service=name,
                            rule="healthcheck",
                            message=(
                                f"Healthcheck timeout ({timeout}) exceeds maximum timeout "
                                f"({conf.max_timeout_seconds}s)"
                            ),
                        )
                    )

        if "non_root_user" in effective.require and not svc.get("user"):
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="non_root_user",
                    message="Running as non-root user (e.g., user: '1000:1000') is required",
                )
            )

        if "project_labels" in effective.require and not svc.get("labels"):
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="project_labels",
                    message="Project labels are required",
                )
            )

        if "no_new_privileges" in effective.require:
            security_opt = svc.get("security_opt", []) or []
            if not _has_no_new_privileges([str(opt) for opt in security_opt]):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="no_new_privileges",
                        message=(
                            "security_opt must include no-new-privileges:true "
                            "to prevent in-container privilege escalation"
                        ),
                    )
                )

        if "drop_all_capabilities" in effective.require:
            cap_drop = svc.get("cap_drop", []) or []
            if "ALL" not in cap_drop and "all" not in cap_drop:
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="drop_all_capabilities",
                        message="cap_drop must include ALL",
                    )
                )

        if "read_only_root_filesystem" in effective.require and svc.get("read_only") is not True:
            violations.append(
                PolicyViolation(
                    service=name,
                    rule="read_only_root_filesystem",
                    message="read_only: true is required for the root filesystem",
                )
            )

        if "pinned_image_tag" in effective.require:
            image = str(svc.get("image", ""))
            if not image or not _has_pinned_image_tag(image):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="pinned_image_tag",
                        message=(
                            "Image must use an explicit non-latest tag or a digest reference"
                        ),
                    )
                )

        if "pids_limit" in effective.require and effective.pids_limit:
            conf = effective.pids_limit
            pids_limit = svc.get("pids_limit")
            if conf.required and pids_limit is None:
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="pids_limit",
                        message="pids_limit is required",
                    )
                )
            elif (
                conf.max_pids is not None
                and pids_limit is not None
                and int(pids_limit) > conf.max_pids
            ):
                violations.append(
                    PolicyViolation(
                        service=name,
                        rule="pids_limit",
                        message=(
                            f"pids_limit ({pids_limit}) exceeds maximum allowed "
                            f"limit ({conf.max_pids})"
                        ),
                    )
                )

    def _extract_registry(self, image: str) -> str:
        parts = image.split("/")
        first = parts[0]
        if first and len(parts) > 1 and ("." in first or ":" in first or first == "localhost"):
            return first
        return "docker.io"

    def _is_database_image(self, image: str) -> bool:
        db_images = [
            "postgres",
            "mysql",
            "mariadb",
            "redis",
            "mongo",
            "elasticsearch",
            "clickhouse",
        ]
        image_name = image.split("/")[-1].split(":")[0]
        return any(db in image_name for db in db_images)


__all__ = [
    "PolicyEngine",
    "parse_duration_to_seconds",
    "parse_size_to_bytes",
]
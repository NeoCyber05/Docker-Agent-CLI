"""Parity tests for required_secrets — mirrors requiredSecrets.test.ts."""

from docker_agent.tools.shared.required_secrets import (
    GENERIC_WEAK_VALUES,
    find_required_secrets,
    is_weak_secret_value,
)


def test_find_required_secrets_matches_postgres_image() -> None:
    rule = find_required_secrets("postgres:17-alpine")
    assert rule is not None
    assert "POSTGRES_PASSWORD" in rule.required


def test_find_required_secrets_returns_none_for_non_db_image() -> None:
    assert find_required_secrets("nginx:1.27-alpine") is None


def _postgres_rule():
    rule = find_required_secrets("postgres:17-alpine")
    assert rule is not None
    return rule


def _mysql_rule():
    rule = find_required_secrets("mysql:8")
    assert rule is not None
    return rule


def test_is_weak_secret_value_flags_empty_string() -> None:
    assert is_weak_secret_value("POSTGRES_PASSWORD", "", _postgres_rule()) is True


def test_is_weak_secret_value_flags_postgres_for_postgres_password() -> None:
    assert is_weak_secret_value("POSTGRES_PASSWORD", "postgres", _postgres_rule()) is True


def test_is_weak_secret_value_flags_generic_weak_value_password() -> None:
    assert is_weak_secret_value("MYSQL_ROOT_PASSWORD", "password", _mysql_rule()) is True


def test_is_weak_secret_value_does_not_flag_strong_random_value() -> None:
    assert is_weak_secret_value("POSTGRES_PASSWORD", "xK9$mP2vQ7nR4wB8", _postgres_rule()) is False


def test_generic_weak_values_includes_common_defaults() -> None:
    assert "password" in GENERIC_WEAK_VALUES
    assert "secret" in GENERIC_WEAK_VALUES
    assert "admin" in GENERIC_WEAK_VALUES
    assert "changeme" in GENERIC_WEAK_VALUES
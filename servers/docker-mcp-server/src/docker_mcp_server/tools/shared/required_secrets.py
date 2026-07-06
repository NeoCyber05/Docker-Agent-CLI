"""Required secret rules by database image.

Parity: ``src/tools/shared/requiredSecrets.ts``.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field


def _random_password() -> str:
    return secrets.token_urlsafe(24)


GENERIC_WEAK_VALUES: tuple[str, ...] = (
    "",
    "password",
    "secret",
    "admin",
    "changeme",
    "test",
    "example",
    "root",
    "123456",
    "password123",
)


@dataclass
class RequiredSecretRule:
    image_pattern: re.Pattern[str]
    required: list[str]
    optional: list[str] | None = None
    safe_defaults: dict[str, Callable[[], str]] = field(default_factory=dict)
    weak_values: list[str] | None = None


REQUIRED_SECRETS_BY_IMAGE: list[RequiredSecretRule] = [
    RequiredSecretRule(
        image_pattern=re.compile(r"^postgres(:|$)"),
        required=["POSTGRES_PASSWORD"],
        optional=["POSTGRES_USER", "POSTGRES_DB"],
        safe_defaults={"POSTGRES_PASSWORD": _random_password},
        weak_values=["postgres", "postgres123", "pg", "postgresql"],
    ),
    RequiredSecretRule(
        image_pattern=re.compile(r"^mysql(:|$)"),
        required=["MYSQL_ROOT_PASSWORD"],
        safe_defaults={"MYSQL_ROOT_PASSWORD": _random_password},
        weak_values=["mysql", "mysql123", "root"],
    ),
    RequiredSecretRule(
        image_pattern=re.compile(r"^mariadb(:|$)"),
        required=["MARIADB_ROOT_PASSWORD"],
        safe_defaults={"MARIADB_ROOT_PASSWORD": _random_password},
        weak_values=["mariadb", "mariadb123", "root"],
    ),
    RequiredSecretRule(
        image_pattern=re.compile(r"^mongo(:|$)"),
        required=["MONGO_INITDB_ROOT_PASSWORD"],
        optional=["MONGO_INITDB_ROOT_USERNAME"],
        safe_defaults={"MONGO_INITDB_ROOT_PASSWORD": _random_password},
        weak_values=["mongo", "mongo123", "mongoadmin"],
    ),
    RequiredSecretRule(
        image_pattern=re.compile(r"^redis(:|$)"),
        required=[],
    ),
]


def find_required_secrets(image: str) -> RequiredSecretRule | None:
    """Return the first matching required-secret rule for an image."""
    return next(
        (rule for rule in REQUIRED_SECRETS_BY_IMAGE if rule.image_pattern.search(image)),
        None,
    )


def is_weak_secret_value(key: str, value: str, rule: RequiredSecretRule) -> bool:
    """Return True when a secret value looks weak or generic."""
    lowered = value.strip().lower()
    if lowered == key.lower():
        return True
    if lowered in GENERIC_WEAK_VALUES:
        return True
    return bool(rule.weak_values and lowered in rule.weak_values)


__all__ = [
    "GENERIC_WEAK_VALUES",
    "REQUIRED_SECRETS_BY_IMAGE",
    "RequiredSecretRule",
    "find_required_secrets",
    "is_weak_secret_value",
]

"""Secret-key detection, HMAC hashing, and log scrubbing.

Parity: ``src/state/secretRedactor.ts:1-41``.
"""

import hashlib
import hmac
import re

from docker_agent.types.stack import EnvSnapshot

SECRET_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|bearer|auth)\b(?:[_-]|$)",
    re.IGNORECASE,
)


def should_redact(key: str) -> bool:
    """Return True if ``key`` matches the secret-key regex."""
    return bool(SECRET_KEY_PATTERN.search(key))


def hash_secret(value: str, salt: str) -> str:
    """HMAC-SHA-256 of ``value`` keyed by ``salt``, returned as lowercase hex.

    The salt is currently the ``stack_name`` so that identical secret values
    across different stacks have different hashes.
    """
    return hmac.new(
        salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def redact_env(env: dict[str, str], stack_name: str) -> EnvSnapshot:
    """Split ``env`` into visible values and secret key hashes."""
    visible: dict[str, str] = {}
    secret_keys: list[str] = []
    secret_hashes_by_key: dict[str, str] = {}

    for key, value in env.items():
        if should_redact(key):
            secret_keys.append(key)
            secret_hashes_by_key[key] = hash_secret(value, stack_name)
        else:
            visible[key] = value

    return EnvSnapshot.model_validate(
        {
            "visible": visible,
            "secret_keys": secret_keys,
            "secret_hashes_by_key": secret_hashes_by_key,
        }
    )


def _escape_regex(s: str) -> str:
    """Escape regex metacharacters in ``s``."""
    return re.escape(s)


def scrub_line(line: str, known_secret_keys: set[str]) -> str:
    """Replace known ``KEY=<value>`` patterns in ``line`` with ``KEY=***``.

    Value may be double-quoted, single-quoted, or unquoted. Repeats for every
    known key. Mirrors ``scrubLine`` in the TS source.
    """
    result = line
    for key in known_secret_keys:
        pattern = re.compile(
            rf"{_escape_regex(key)}=(\"[^\"]*\"|'[^']*'|[^\s]+)",
        )
        result = pattern.sub(f"{key}=***", result)
    return result


__all__ = [
    "SECRET_KEY_PATTERN",
    "hash_secret",
    "redact_env",
    "scrub_line",
    "should_redact",
]
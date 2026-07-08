"""Secret-key detection, HMAC hashing, and log scrubbing.
"""

import hashlib
import hmac
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SECRET_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|bearer|auth)\b(?:[_-]|$)",
    re.IGNORECASE,
)

CREDENTIAL_URI_PATTERN = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s:/@'\"]+:[^\s@/'\"]+@"
)

REDACTION_PLACEHOLDER = "***"

class EnvSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    visible: dict[str, str] = Field(default_factory=dict)
    secret_keys: list[str] = Field(default_factory=list, alias="secretKeys")
    secret_hashes_by_key: dict[str, str] = Field(
        default_factory=dict,
        alias="secretHashesByKey",
    )


def should_redact(key: str) -> bool:
    """Return True if ``key`` matches the secret-key regex."""
    return bool(SECRET_KEY_PATTERN.search(key))


def looks_like_credential_uri(value: str) -> bool:
    """Return True when ``value`` embeds user:password@ in a URI scheme."""
    return bool(CREDENTIAL_URI_PATTERN.search(value))


def _mask_credential_uris(text: str) -> str:
    return CREDENTIAL_URI_PATTERN.sub(
        lambda m: f"{m.group('scheme')}{REDACTION_PLACEHOLDER}@",
        text,
    )


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
    return _mask_credential_uris(result)


def redact_text(value: str) -> str:
    """Redact secret-like key/value patterns inside free-form text."""
    result = re.sub(
        r'"([^"]+)"(\s*:\s*)"([^"]*)"',
        lambda m: f'"{m.group(1)}"{m.group(2)}"{REDACTION_PLACEHOLDER}"'
        if should_redact(m.group(1))
        else m.group(0),
        value,
    )
    result = re.sub(
        r'(\b\w+\b)(=)("[^"]*"|\'[^\']*\'|[^\s,}]+)',
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTION_PLACEHOLDER}"
        if should_redact(m.group(1))
        else m.group(0),
        result,
    )
    return _mask_credential_uris(result)


def redact_value_deep(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value_deep(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if should_redact(key):
                out[key] = REDACTION_PLACEHOLDER
            else:
                out[key] = redact_value_deep(item)
        return out
    return value


__all__ = [
    "CREDENTIAL_URI_PATTERN",
    "REDACTION_PLACEHOLDER",
    "SECRET_KEY_PATTERN",
    "EnvSnapshot",
    "hash_secret",
    "looks_like_credential_uri",
    "redact_env",
    "redact_text",
    "redact_value_deep",
    "scrub_line",
    "should_redact",
]


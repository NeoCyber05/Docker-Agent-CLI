"""
Env-file parsing, reading, writing, and merging.
"""

import os
from collections.abc import Mapping
from pathlib import Path

EnvValue = str | int | bool


def _parse_env_value(value: str) -> str | None:
    """Parse the right-hand side of an env line.

    Returns ``None`` when the line should be skipped (unclosed quote,
    garbage after quoted value, etc.).
    """
    value = value.strip()
    if not value:
        return ""

    if value.startswith('"') or value.startswith("'"):
        quote = value[0]
        close = value.find(quote, 1)
        if close < 0:
            return None
        trailing = value[close + 1 :].strip()
        if trailing and not trailing.startswith("#"):
            return None
        return value[1:close]

    # unquoted value â€” inline comment only if preceded by a space
    hash_idx = value.find(" #")
    if hash_idx >= 0:
        value = value[:hash_idx]
    return value.strip()


def parse_env_file(content: str) -> dict[str, str]:
    """Parse ``.env`` style content into a key/value map.

    Does NOT support multiline values, escape sequences, or ``export`` prefix.
    """
    out: dict[str, str] = {}
    for raw_line in content.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.index("=")
        if eq <= 0:
            continue
        key = line[:eq].strip()
        parsed_value = _parse_env_value(line[eq + 1 :])
        if parsed_value is None:
            continue
        out[key] = parsed_value
    return out


def _assert_supported_env_file_value(key: str, value: str) -> None:
    """Reject values containing characters we cannot safely round-trip."""
    if any(ch in value for ch in ('"', "\n", "\r", "\0")):
        raise ValueError(f"Unsupported env_file value for {key}")


def _generate_env_file_content(values: dict[str, str]) -> str:
    """Serialize a value map into ``.env`` file content."""
    lines: list[str] = []
    for key, value in values.items():
        _assert_supported_env_file_value(key, value)
        needs_quotes = bool(value.strip() and (value[0] == "#" or any(c.isspace() for c in value)))
        if needs_quotes:
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")
    if lines:
        return "\n".join(lines) + "\n"
    return ""


def read_env_file(file_path: str | os.PathLike[str]) -> dict[str, str]:
    """Read and parse an env file; return ``{}`` if it does not exist."""
    path = Path(file_path)
    if not path.exists():
        return {}
    return parse_env_file(path.read_text(encoding="utf-8"))


def render_env_file(values: dict[str, str]) -> str:
    """Serialize a value map into ``.env`` file content."""
    return _generate_env_file_content(values)


def write_env_file(
    file_path: str | os.PathLike[str], values: dict[str, str]
) -> None:
    """Write ``values`` to an env file with mode ``0o600``.

    Creates parent directories recursively. NOT atomic â€” matches the TS
    implementation.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_env_file(values), encoding="utf-8")
    os.chmod(path, 0o600)


def merge_env(
    from_env_file: dict[str, str], inline_environment: Mapping[str, EnvValue]
) -> dict[str, str]:
    """Merge env-file values with inline values; inline wins, coercion to string."""
    merged = dict(from_env_file)
    for key, value in inline_environment.items():
        merged[key] = str(value)
    return merged


__all__ = [
    "EnvValue",
    "merge_env",
    "parse_env_file",
    "read_env_file",
    "render_env_file",
    "write_env_file",
]

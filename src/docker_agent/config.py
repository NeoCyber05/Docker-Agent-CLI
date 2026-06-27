"""User/project configuration and path helpers.

Parity: ``src/config.ts:1-73``.
"""

import json
import os
import sys
from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["gemini", "openai", "ollama", "openrouter"]
ThemeName = Literal["dark", "light"]
PROVIDER_NAMES: list[ProviderName] = ["gemini", "openai", "ollama", "openrouter"]
STACK_STATES_DIR_NAME = "docker-stacks"


def is_valid_provider(value: object) -> bool:
    return isinstance(value, str) and value in PROVIDER_NAMES


class UserDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    auto_approve_non_destructive: bool = Field(
        default=False, alias="autoApproveNonDestructive"
    )
    missing_project_policy: Literal["use-global", "deny"] = Field(
        default="deny", alias="missingProjectPolicy"
    )


class UserConfig(BaseModel):
    """Contents of ``~/.docker-agent/config.json``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    provider: ProviderName = "gemini"
    model: str | None = None
    theme: ThemeName = "dark"
    defaults: UserDefaults = Field(default_factory=UserDefaults)

    @pydantic.field_validator("provider", mode="before")
    @classmethod
    def _validate_provider(cls, v: object) -> ProviderName:
        if not is_valid_provider(v):
            raise ValueError(f"invalid provider: {v}")
        return v  # type: ignore[return-value]


def user_config_path() -> str:
    return os.environ.get(
        "DOCKER_AGENT_CONFIG",
        str(Path.home() / ".docker-agent" / "config.json"),
    )


def project_state_dir(cwd: str | os.PathLike[str] | None = None) -> str:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return str(base / ".docker-agent")


def stack_states_dir(cwd: str | os.PathLike[str] | None = None) -> str:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return str(base / STACK_STATES_DIR_NAME)


def stack_state_yaml_path(
    stack_name: str, cwd: str | os.PathLike[str] | None = None
) -> str:
    return str(Path(stack_states_dir(cwd)) / f"{stack_name}.yaml")


def _known_user_config_keys() -> set[str]:
    keys: set[str] = set()
    for name, field in UserConfig.model_fields.items():
        keys.add(name)
        if field.alias:
            keys.add(field.alias)
    return keys


def _strip_unknown_user_config_keys(raw: dict[str, object]) -> dict[str, object]:
    allowed = _known_user_config_keys()
    return {key: value for key, value in raw.items() if key in allowed}


def load_user_config(path: str | os.PathLike[str] | None = None) -> UserConfig:
    """Load user config from ``path`` or ``user_config_path()``.

    Missing file → defaults. Corrupt JSON → warn to stderr and return defaults.
    """
    target = Path(path) if path else Path(user_config_path())
    if not target.exists():
        return UserConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        print(
            f"[docker-agent] Failed to load user config, using defaults: {err}",
            file=sys.stderr,
        )
        return UserConfig()

    # Sanitize provider before pydantic sees it; invalid provider falls back.
    provider = raw.get("provider")
    if not is_valid_provider(provider):
        raw = {**raw, "provider": "gemini"}

    try:
        return UserConfig.model_validate(raw)
    except pydantic.ValidationError:
        stripped = _strip_unknown_user_config_keys(raw)
        try:
            return UserConfig.model_validate(stripped)
        except pydantic.ValidationError as err:
            print(
                f"[docker-agent] Failed to load user config, using defaults: {err}",
                file=sys.stderr,
            )
            return UserConfig()


def resolve_provider(
    *, flag: str | None = None, config: UserConfig | None = None
) -> ProviderName:
    """Resolve provider: CLI flag → env → config → default."""
    if flag and is_valid_provider(flag):
        return flag  # type: ignore[return-value]
    env = os.environ.get("DOCKER_AGENT_PROVIDER")
    if env and is_valid_provider(env):
        return env  # type: ignore[return-value]
    effective = config if config is not None else load_user_config()
    return effective.provider


__all__ = [
    "PROVIDER_NAMES",
    "STACK_STATES_DIR_NAME",
    "ProviderName",
    "ThemeName",
    "UserConfig",
    "UserDefaults",
    "is_valid_provider",
    "load_user_config",
    "project_state_dir",
    "resolve_provider",
    "stack_state_yaml_path",
    "stack_states_dir",
    "user_config_path",
]
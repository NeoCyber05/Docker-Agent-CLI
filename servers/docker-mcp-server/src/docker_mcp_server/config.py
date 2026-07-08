"""
User/project configuration and path helpers.
"""

import contextlib
import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["gemini", "openai", "ollama", "openrouter"]
PROVIDER_NAMES: list[ProviderName] = ["gemini", "openai", "ollama", "openrouter"]
STACK_STATES_DIR_NAME = "docker-stacks"

_PROVIDER_DEFAULT_MODELS: dict[ProviderName, tuple[str, str]] = {
    "gemini": ("GEMINI_MODEL", "gemini-2.0-flash"),
    "openai": ("OPENAI_MODEL", "gpt-4o-mini"),
    "openrouter": ("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    "ollama": ("OLLAMA_MODEL", "qwen2.5:14b"),
}


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

    Missing file â†’ defaults. Corrupt JSON â†’ warn to stderr and return defaults.
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
    """Resolve provider: CLI flag â†’ env â†’ config â†’ default."""
    if flag and is_valid_provider(flag):
        return flag  # type: ignore[return-value]
    env = os.environ.get("DOCKER_AGENT_PROVIDER")
    if env and is_valid_provider(env):
        return env  # type: ignore[return-value]
    effective = config if config is not None else load_user_config()
    return effective.provider


def resolve_default_model(
    provider: ProviderName,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return the provider's fallback model (env override, then built-in default)."""
    effective_env = env if env is not None else os.environ
    env_var, fallback = _PROVIDER_DEFAULT_MODELS[provider]
    return effective_env.get(env_var) or fallback


def resolve_display_model(
    provider: str | None,
    model: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Model label for UI: explicit override, else provider default."""
    if model:
        return model
    if provider and is_valid_provider(provider):
        return resolve_default_model(provider, env)  # type: ignore[arg-type]
    return None


def save_user_config(
    config: UserConfig,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Persist user config to ``path`` or ``user_config_path()``."""
    target = Path(path) if path else Path(user_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json", by_alias=True)
    tmp_path = Path(f"{target}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(target))
    except Exception as err:  # noqa: BLE001
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        print(
            f"[docker-agent] Failed to save user config: {err}",
            file=sys.stderr,
        )


def persist_model_choice(
    provider: ProviderName,
    model: str,
    *,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Merge provider + model into the user config file."""
    config_path = Path(path) if path else Path(user_config_path())
    existing = load_user_config(config_path)
    updated = existing.model_copy(update={"provider": provider, "model": model})
    save_user_config(updated, config_path)


__all__ = [
    "PROVIDER_NAMES",
    "STACK_STATES_DIR_NAME",
    "ProviderName",
    "UserConfig",
    "UserDefaults",
    "is_valid_provider",
    "load_user_config",
    "persist_model_choice",
    "project_state_dir",
    "resolve_default_model",
    "resolve_display_model",
    "resolve_provider",
    "save_user_config",
    "stack_state_yaml_path",
    "stack_states_dir",
    "user_config_path",
]

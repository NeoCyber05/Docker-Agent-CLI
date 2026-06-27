"""Parity tests for config — mirrors src/config.ts:1-73."""

import json
from pathlib import Path

import pytest

from src.config import (
    UserConfig,
    is_valid_provider,
    load_user_config,
    project_state_dir,
    resolve_provider,
    stack_state_yaml_path,
    user_config_path,
)

# --- provider validation -------------------------------------------------

def test_is_valid_provider_exact_match() -> None:
    assert is_valid_provider("gemini")
    assert is_valid_provider("openai")
    assert is_valid_provider("ollama")
    assert is_valid_provider("openrouter")
    assert not is_valid_provider("Gemini")
    assert not is_valid_provider("bogus")
    assert not is_valid_provider(123)


# --- UserConfig defaults -------------------------------------------------

def test_user_config_defaults() -> None:
    cfg = UserConfig()
    assert cfg.provider == "gemini"
    assert cfg.model is None
    assert cfg.defaults.auto_approve_non_destructive is False
    assert cfg.defaults.missing_project_policy == "deny"


def test_user_config_accepts_use_global_policy() -> None:
    cfg = UserConfig(defaults={"missing_project_policy": "use-global"})
    assert cfg.defaults.missing_project_policy == "use-global"


def test_user_config_rejects_invalid_provider() -> None:
    with pytest.raises(ValueError):
        UserConfig(provider="bogus")  # type: ignore[arg-type]


# --- path helpers --------------------------------------------------------

def test_project_state_dir_default_uses_cwd(tmp_path: Path) -> None:
    assert project_state_dir(tmp_path) == str(tmp_path / ".docker-agent")


def test_stack_state_yaml_path(tmp_path: Path) -> None:
    assert stack_state_yaml_path("web", tmp_path) == str(tmp_path / "docker-stacks" / "web.yaml")


# --- load_user_config ----------------------------------------------------

def test_load_user_config_missing_returns_defaults(tmp_path: Path) -> None:
    cfg = load_user_config(tmp_path / "does-not-exist.json")
    assert cfg.provider == "gemini"
    assert cfg.model is None


def test_load_user_config_merges_existing_values(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "openai", "model": "gpt-4o"}))
    cfg = load_user_config(p)
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o"
    # defaults still filled
    assert cfg.defaults.auto_approve_non_destructive is False


def test_load_user_config_ignores_invalid_provider(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "bogus"}))
    cfg = load_user_config(p)
    assert cfg.provider == "gemini"


def test_load_user_config_corrupt_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text("not json")
    cfg = load_user_config(p)
    assert cfg.provider == "gemini"


# --- resolve_provider ----------------------------------------------------

def test_resolve_provider_priority_flag_over_env() -> None:
    cfg = UserConfig(provider="gemini")
    assert resolve_provider(flag="openai", config=cfg) == "openai"


def test_resolve_provider_env_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_PROVIDER", "ollama")
    cfg = UserConfig(provider="gemini")
    assert resolve_provider(config=cfg) == "ollama"


def test_resolve_provider_config_fallback() -> None:
    cfg = UserConfig(provider="openrouter")
    assert resolve_provider(config=cfg) == "openrouter"


def test_resolve_provider_invalid_flag_ignored() -> None:
    cfg = UserConfig(provider="gemini")
    assert resolve_provider(flag="bogus", config=cfg) == "gemini"


def test_resolve_provider_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_AGENT_CONFIG", str(tmp_path / "config.json"))
    assert user_config_path() == str(tmp_path / "config.json")
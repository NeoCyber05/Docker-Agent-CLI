"""Parity tests for apiKeyStore."""

import pytest

from docker_agent.vault.api_key_store import (
    MemoryApiKeyStore,
    describe_api_key_status,
    resolve_stored_api_key,
)


@pytest.mark.asyncio
async def test_resolve_stored_api_key_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    store = MemoryApiKeyStore({"openai": "saved-key"})
    assert await resolve_stored_api_key("openai", store=store) == "env-key"


@pytest.mark.asyncio
async def test_resolve_stored_api_key_falls_back_to_store() -> None:
    store = MemoryApiKeyStore({"openai": "saved-key"})
    assert await resolve_stored_api_key("openai", env={}, store=store) == "saved-key"


@pytest.mark.asyncio
async def test_describe_api_key_status() -> None:
    store = MemoryApiKeyStore({"gemini": "g-key"})
    statuses = await describe_api_key_status(store, env={})
    gemini = next(s for s in statuses if s.provider == "gemini")
    openai = next(s for s in statuses if s.provider == "openai")
    assert gemini.state == "set"
    assert gemini.source == "saved"
    assert openai.state == "unset"

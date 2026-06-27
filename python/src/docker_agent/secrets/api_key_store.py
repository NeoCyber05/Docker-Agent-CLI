"""API key storage abstraction.

Parity: ``src/secrets/apiKeyStore.ts``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

ApiKeyProviderName = Literal["openai", "gemini", "openrouter"]
API_KEY_PROVIDERS: list[ApiKeyProviderName] = ["openai", "gemini", "openrouter"]
ApiKeySource = Literal["env", "saved"]


class ApiKeyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ApiKeyProviderName
    state: str  # "set" | "unset"
    source: ApiKeySource | None = None


@runtime_checkable
class ApiKeyStore(Protocol):
    async def get(self, provider: ApiKeyProviderName) -> str | None: ...
    async def set(self, provider: ApiKeyProviderName, value: str) -> None: ...
    async def delete(self, provider: ApiKeyProviderName) -> None: ...
    async def has(self, provider: ApiKeyProviderName) -> bool: ...


def api_key_env_var(provider: ApiKeyProviderName) -> str:
    return {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }[provider]


async def resolve_stored_api_key(
    provider: ApiKeyProviderName,
    env: Mapping[str, str] | None = None,
    store: ApiKeyStore | None = None,
) -> str | None:
    effective_env = env if env is not None else os.environ
    env_value = effective_env.get(api_key_env_var(provider), "").strip()
    if env_value:
        return env_value
    if store is not None:
        return await store.get(provider)
    return None


async def describe_api_key_status(
    store: ApiKeyStore,
    env: Mapping[str, str] | None = None,
) -> list[ApiKeyStatus]:
    effective_env = env if env is not None else os.environ
    statuses: list[ApiKeyStatus] = []
    for provider in API_KEY_PROVIDERS:
        env_value = effective_env.get(api_key_env_var(provider), "").strip()
        if env_value:
            statuses.append(ApiKeyStatus(provider=provider, state="set", source="env"))
        elif await store.has(provider):
            statuses.append(ApiKeyStatus(provider=provider, state="set", source="saved"))
        else:
            statuses.append(ApiKeyStatus(provider=provider, state="unset"))
    return statuses


class MemoryApiKeyStore:
    """In-memory store for tests."""

    def __init__(self, initial: dict[ApiKeyProviderName, str] | None = None) -> None:
        self._values: dict[ApiKeyProviderName, str] = dict(initial or {})

    async def get(self, provider: ApiKeyProviderName) -> str | None:
        return self._values.get(provider)

    async def set(self, provider: ApiKeyProviderName, value: str) -> None:
        self._values[provider] = value

    async def delete(self, provider: ApiKeyProviderName) -> None:
        self._values.pop(provider, None)

    async def has(self, provider: ApiKeyProviderName) -> bool:
        return provider in self._values


class UnsupportedApiKeyStore:
    """Fallback when no credential backend is available."""

    async def get(self, provider: ApiKeyProviderName) -> str | None:
        return None

    async def set(self, provider: ApiKeyProviderName, value: str) -> None:
        raise RuntimeError("No persistent credential backend is available on this platform")

    async def delete(self, provider: ApiKeyProviderName) -> None:
        return None

    async def has(self, provider: ApiKeyProviderName) -> bool:
        return False


def create_api_key_store() -> ApiKeyStore:
    """Create the best available persistent credential store.

    Uses the ``keyring`` package when installed (cross-platform: Windows DPAPI,
    macOS Keychain, Linux Secret Service). Falls back to ``UnsupportedApiKeyStore``.
    """
    try:
        import keyring

        class KeyringApiKeyStore:
            _SERVICE = "docker-agent"

            async def get(self, provider: ApiKeyProviderName) -> str | None:
                value = keyring.get_password(self._SERVICE, provider)
                return value if value else None

            async def set(self, provider: ApiKeyProviderName, value: str) -> None:
                keyring.set_password(self._SERVICE, provider, value)

            async def delete(self, provider: ApiKeyProviderName) -> None:
                keyring.delete_password(self._SERVICE, provider)

            async def has(self, provider: ApiKeyProviderName) -> bool:
                return await self.get(provider) is not None

        return KeyringApiKeyStore()
    except Exception:
        return UnsupportedApiKeyStore()


__all__ = [
    "API_KEY_PROVIDERS",
    "ApiKeyProviderName",
    "ApiKeySource",
    "ApiKeyStatus",
    "ApiKeyStore",
    "MemoryApiKeyStore",
    "UnsupportedApiKeyStore",
    "api_key_env_var",
    "create_api_key_store",
    "describe_api_key_status",
    "resolve_stored_api_key",
]
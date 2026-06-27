"""Provider connectivity probes.

Parity: ``src/services/providerStatus.ts``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from src.config import PROVIDER_NAMES, ProviderName
from src.services.api.types import Provider
from src.vault.api_key_store import (
    ApiKeyProviderName,
    ApiKeyStore,
    is_api_key_provider_name,
    resolve_stored_api_key,
)


@dataclass
class ProviderStatus:
    provider: ProviderName
    connected: bool
    model_count: int | None = None
    reason: str | None = None


async def is_api_key_provider_connected(
    provider: ProviderName,
    api_key_store: ApiKeyStore,
    env: Mapping[str, str] | None = None,
) -> bool:
    if not is_api_key_provider_name(provider):
        return False
    effective_env = env if env is not None else os.environ
    api_provider = cast(ApiKeyProviderName, provider)
    return bool(await resolve_stored_api_key(api_provider, effective_env, api_key_store))


async def get_provider_statuses(
    *,
    api_key_store: ApiKeyStore,
    providers: dict[ProviderName, Provider],
    env: Mapping[str, str] | None = None,
) -> list[ProviderStatus]:
    effective_env = env if env is not None else os.environ
    statuses: list[ProviderStatus] = []
    for provider in PROVIDER_NAMES:
        if is_api_key_provider_name(provider):
            connected = await is_api_key_provider_connected(
                provider, api_key_store, effective_env
            )
            statuses.append(
                ProviderStatus(
                    provider=provider,
                    connected=connected,
                    reason=None if connected else "API key not set",
                )
            )
            continue
        instance = providers.get("ollama")
        if instance is None or not hasattr(instance, "list_models"):
            statuses.append(
                ProviderStatus(
                    provider=provider,
                    connected=False,
                    reason="Cannot probe Ollama",
                )
            )
            continue
        try:
            list_models = getattr(instance, "list_models", None)
            if list_models is None:
                raise RuntimeError("list_models not available")
            models = await list_models()
            statuses.append(
                ProviderStatus(
                    provider=provider,
                    connected=True,
                    model_count=len(models),
                )
            )
        except Exception as err:  # noqa: BLE001
            statuses.append(
                ProviderStatus(
                    provider=provider,
                    connected=False,
                    reason=str(err),
                )
            )
    return statuses


__all__ = [
    "ProviderStatus",
    "get_provider_statuses",
    "is_api_key_provider_connected",
]
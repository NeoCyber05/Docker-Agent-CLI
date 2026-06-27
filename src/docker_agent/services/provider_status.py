"""Provider connectivity probes.

Parity: ``src/services/providerStatus.ts``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from docker_agent.config import PROVIDER_NAMES, ProviderName
from docker_agent.services.api.types import Provider
from docker_agent.vault.api_key_store import (
    ApiKeyProviderName,
    ApiKeyStore,
    is_api_key_provider_name,
    resolve_stored_api_key,
)

PROVIDER_PROBE_TIMEOUT = 5.0  # seconds


@dataclass
class ProviderStatus:
    provider: ProviderName
    connected: bool
    model_count: int | None = None
    reason: str | None = None
    models: list[str] = field(default_factory=list)


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


async def _probe_single_provider(
    provider: ProviderName,
    *,
    api_key_store: ApiKeyStore,
    providers: dict[ProviderName, Provider],
    env: Mapping[str, str],
) -> ProviderStatus:
    """Probe a single provider for connectivity and available models."""
    if is_api_key_provider_name(provider):
        connected = await is_api_key_provider_connected(provider, api_key_store, env)
        if not connected:
            return ProviderStatus(
                provider=provider,
                connected=False,
                reason="API key not set",
            )
        # For API-key providers, try to fetch models
        instance = providers.get(provider)
        if instance is None or not hasattr(instance, "list_models"):
            return ProviderStatus(provider=provider, connected=True)
        list_models = getattr(instance, "list_models", None)
        if list_models is None:
            return ProviderStatus(provider=provider, connected=True)
        try:
            models = await asyncio.wait_for(
                list_models(), timeout=PROVIDER_PROBE_TIMEOUT
            )
            return ProviderStatus(
                provider=provider,
                connected=True,
                model_count=len(models),
                models=list(models),
            )
        except Exception:  # noqa: BLE001
            # Connected (has key) but model listing failed — still connected
            return ProviderStatus(provider=provider, connected=True)

    # Non-API-key provider (Ollama)
    instance = providers.get("ollama")
    if instance is None or not hasattr(instance, "list_models"):
        return ProviderStatus(
            provider=provider,
            connected=False,
            reason="Cannot probe Ollama",
        )
    try:
        list_models = getattr(instance, "list_models", None)
        if list_models is None:
            raise RuntimeError("list_models not available")
        models = await asyncio.wait_for(
            list_models(), timeout=PROVIDER_PROBE_TIMEOUT
        )
        return ProviderStatus(
            provider=provider,
            connected=True,
            model_count=len(models),
            models=list(models),
        )
    except Exception as err:  # noqa: BLE001
        return ProviderStatus(
            provider=provider,
            connected=False,
            reason=str(err),
        )


async def get_provider_statuses(
    *,
    api_key_store: ApiKeyStore,
    providers: dict[ProviderName, Provider],
    env: Mapping[str, str] | None = None,
) -> list[ProviderStatus]:
    effective_env = env if env is not None else os.environ
    statuses = await asyncio.gather(
        *(
            _probe_single_provider(
                provider,
                api_key_store=api_key_store,
                providers=providers,
                env=effective_env,
            )
            for provider in PROVIDER_NAMES
        )
    )
    return list(statuses)


__all__ = [
    "ProviderStatus",
    "get_provider_statuses",
    "is_api_key_provider_connected",
]
"""Model catalog helpers.

Parity: ``src/services/modelCatalog.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from docker_agent.config import PROVIDER_NAMES, ProviderName, is_valid_provider
from docker_agent.services.api.types import Provider
from docker_agent.services.provider_status import ProviderStatus

CatalogRowKind = Literal["header", "model", "connect"]


@dataclass
class CatalogEntryConnected:
    provider: ProviderName
    connected: Literal[True] = True
    models: list[str] | None = None

    def __post_init__(self) -> None:
        if self.models is None:
            self.models = []


@dataclass
class CatalogEntryDisconnected:
    provider: ProviderName
    connected: Literal[False] = False
    reason: str = "Not connected"


CatalogEntry = CatalogEntryConnected | CatalogEntryDisconnected


@dataclass
class CatalogRowHeader:
    kind: Literal["header"] = "header"
    provider: ProviderName = "gemini"
    connected: bool = False


@dataclass
class CatalogRowModel:
    kind: Literal["model"] = "model"
    provider: ProviderName = "gemini"
    model: str = ""


@dataclass
class CatalogRowConnect:
    kind: Literal["connect"] = "connect"
    provider: ProviderName = "gemini"
    reason: str = ""


CatalogRow = CatalogRowHeader | CatalogRowModel | CatalogRowConnect


def parse_provider_model(
    input_text: str,
    default_provider: ProviderName | None = None,
) -> dict[str, ProviderName | str] | None:
    trimmed = input_text.strip()
    if not trimmed:
        return None
    if "/" in trimmed:
        provider_part, model = trimmed.split("/", 1)
        if not is_valid_provider(provider_part) or not model:
            return None
        provider = cast(ProviderName, provider_part)
        return {"provider": provider, "model": model}
    if default_provider is None:
        return None
    return {"provider": default_provider, "model": trimmed}


async def build_model_catalog(
    statuses: list[ProviderStatus],
    providers: dict[ProviderName, Provider],
) -> list[CatalogEntry]:
    status_by_provider = {status.provider: status for status in statuses}
    entries: list[CatalogEntry] = []
    for provider in PROVIDER_NAMES:
        status = status_by_provider.get(provider)
        if status is None or not status.connected:
            entries.append(
                CatalogEntryDisconnected(
                    provider=provider,
                    reason=(status.reason or "Not connected") if status else "Not connected",
                )
            )
            continue
        instance = providers.get(provider)
        if instance is None or not hasattr(instance, "list_models"):
            entries.append(CatalogEntryConnected(provider=provider, models=[]))
            continue
        list_models = getattr(instance, "list_models", None)
        if list_models is None:
            entries.append(CatalogEntryConnected(provider=provider, models=[]))
            continue
        models = await list_models()
        entries.append(CatalogEntryConnected(provider=provider, models=list(models)))
    return entries


PROVIDER_LABELS: dict[ProviderName, str] = {
    "gemini": "Gemini",
    "openai": "OpenAI",
    "ollama": "Ollama",
    "openrouter": "OpenRouter",
}


def provider_label(provider: ProviderName) -> str:
    return PROVIDER_LABELS[provider]


def filter_rows(rows: list[CatalogRow], query: str) -> list[CatalogRow]:
    q = query.strip().lower()
    if not q:
        return rows

    providers_with_matches: set[ProviderName] = set()
    matching_rows: list[CatalogRow] = []

    for row in rows:
        if row.kind == "header":
            continue
        label = provider_label(row.provider).lower()
        haystack = f"{label} {row.model}".lower() if row.kind == "model" else label
        if q in haystack:
            providers_with_matches.add(row.provider)
            matching_rows.append(row)

    result: list[CatalogRow] = []
    for provider in PROVIDER_NAMES:
        if provider not in providers_with_matches:
            continue
        header = next((r for r in rows if r.kind == "header" and r.provider == provider), None)
        if header:
            result.append(header)
        result.extend(row for row in matching_rows if row.provider == provider)
    return result


def flatten_catalog(catalog: list[CatalogEntry]) -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    for entry in catalog:
        rows.append(CatalogRowHeader(provider=entry.provider, connected=entry.connected))
        if entry.connected:
            for model in entry.models or []:
                rows.append(CatalogRowModel(provider=entry.provider, model=model))
        else:
            reason = entry.reason if isinstance(entry, CatalogEntryDisconnected) else ""
            rows.append(CatalogRowConnect(provider=entry.provider, reason=reason))
    return rows


__all__ = [
    "CatalogEntry",
    "CatalogRow",
    "CatalogRowConnect",
    "CatalogRowHeader",
    "CatalogRowModel",
    "build_model_catalog",
    "filter_rows",
    "flatten_catalog",
    "parse_provider_model",
    "provider_label",
]
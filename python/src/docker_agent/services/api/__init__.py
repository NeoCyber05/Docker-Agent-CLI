"""LLM provider API layer."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from docker_agent.config import ProviderName
from docker_agent.services.api.providers import (
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from docker_agent.services.api.tool_schema import (
    to_gemini_function_declaration,
    to_json_schema,
    to_openai_function,
)
from docker_agent.services.api.types import (
    CallModelParams,
    Provider,
    ProviderEvent,
    ToolSchema,
    UsageInfo,
)

if TYPE_CHECKING:
    from docker_agent.secrets.api_key_store import ApiKeyStore


def resolve_provider_for_request(
    name: ProviderName,
    env: Mapping[str, str] | None = None,
    *,
    api_key_store: ApiKeyStore | None = None,
) -> Provider:
    """Instantiate a provider for the given name."""
    effective_env = dict(env if env is not None else os.environ)
    match name:
        case "gemini":
            return GeminiProvider(effective_env, api_key_store)
        case "openai":
            return OpenAIProvider(effective_env, api_key_store)
        case "ollama":
            return OllamaProvider(effective_env)
        case "openrouter":
            return OpenRouterProvider(effective_env, api_key_store)
        case _:
            raise ValueError(f"unknown provider: {name}")


__all__ = [
    "CallModelParams",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "Provider",
    "ProviderEvent",
    "ToolSchema",
    "UsageInfo",
    "to_gemini_function_declaration",
    "to_json_schema",
    "to_openai_function",
    "resolve_provider_for_request",
]
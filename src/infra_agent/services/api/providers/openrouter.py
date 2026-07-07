"""OpenRouter provider adapter.

Parity: ``src/services/api/providers/openrouter.ts``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from infra_agent.services.api.providers.openai import OpenAIProvider
from infra_agent.services.api.types import CallModelParams, ErrorEvent, ProviderEvent
from infra_agent.vault.api_key_store import ApiKeyStore, resolve_stored_api_key

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/docker-agent-cli",
    "X-Title": "docker-agent",
}


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        env: dict[str, str] | None = None,
        api_key_store: ApiKeyStore | None = None,
    ) -> None:
        self._env = env or dict(os.environ)
        self._api_key_store = api_key_store
        self._base_url = self._env.get("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL

    def _make_client(self, api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            default_headers=OPENROUTER_HEADERS,
        )

    async def list_models(self) -> list[str]:
        import asyncio

        api_key = await resolve_stored_api_key("openrouter", self._env, self._api_key_store)
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        client = self._make_client(api_key)
        res = await asyncio.to_thread(client.models.list)
        return sorted(
            m.id for m in res.data if isinstance(getattr(m, "id", None), str) and m.id
        )

    async def stream(self, params: CallModelParams) -> AsyncIterator[ProviderEvent]:
        api_key = await resolve_stored_api_key("openrouter", self._env, self._api_key_store)
        if not api_key:
            yield ErrorEvent(error=RuntimeError("OPENROUTER_API_KEY not set"))
            return

        model = params.model or self._env.get("OPENROUTER_MODEL") or "openai/gpt-4o-mini"
        internal_env = dict(self._env)
        internal_env["OPENAI_BASE_URL"] = self._base_url
        internal_env["OPENAI_API_KEY"] = api_key
        internal = OpenAIProvider(
            env=internal_env,
            api_key_store=self._api_key_store,
            client=self._make_client(api_key),
        )
        params_with_model = params.model_copy(update={"model": model})
        async for event in internal.stream(params_with_model):
            yield event
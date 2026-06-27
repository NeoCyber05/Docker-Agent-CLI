"""Current backend — delegates to the query() generator.

Parity: ``src/backend/CurrentBackend.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from docker_agent.backend.agent_backend import BackendQueryParams
from docker_agent.query import query
from docker_agent.types.events import LoopEvent


class CurrentBackend:
    name = "current"

    async def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]:
        async for ev in query(
            messages=params.messages,
            ctx=params.ctx,
            provider=params.provider,
            model=params.model,
        ):
            yield ev
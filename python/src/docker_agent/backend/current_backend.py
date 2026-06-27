"""Current backend stub — full port is Plan 08."""

from __future__ import annotations

from collections.abc import AsyncIterator

from docker_agent.backend.agent_backend import BackendQueryParams
from docker_agent.types.events import LoopEvent


class CurrentBackend:
    name = "current"

    async def query(self, params: BackendQueryParams) -> AsyncIterator[LoopEvent]:
        raise NotImplementedError("CurrentBackend port is Plan 08")
        yield  # pragma: no cover
"""Docker service types used by Phase 2 state modules.

Phase 3 will expand this file with the real EngineClient implementation and
ContainerInspect zod-equivalent pydantic models. For Phase 2, only the read
methods required by drift detection are declared here as a Protocol.
"""

from typing import Any, Protocol


class ContainerInspect(Protocol):
    """Minimal duck-type for a container inspect result.

    The drift detector needs:
    - Config.Image, Config.Cmd, Config.Env, Config.Labels
    - HostConfig.Binds
    - NetworkSettings.Ports
    - State.Status
    """

    Config: Any
    HostConfig: Any
    NetworkSettings: Any
    State: Any


class EngineClient(Protocol):
    """Phase-2 read-only subset of the Docker engine client."""

    async def list_containers(
        self, *, all: bool = False, filters: dict[str, list[str]] | None = None
    ) -> list[dict[str, Any]]: ...

    async def inspect(self, container_id: str) -> ContainerInspect: ...
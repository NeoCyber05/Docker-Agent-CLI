"""EngineClient implementation over docker-py.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from collections.abc import AsyncIterator, Iterator
from typing import Any

from docker_mcp_server.services.docker.types import (
    ContainerInspect,
    ContainerStats,
    ContainerSummary,
    EngineClient,
    ImageInspect,
    ImageSummary,
)
from docker_mcp_server.utils.sync_bridge import aiter_in_thread


def _load_docker_py() -> Any:
    """Load docker-py even when test paths shadow the top-level ``docker`` name."""
    cached = sys.modules.get("docker")
    if cached is not None and hasattr(cached, "errors"):
        return cached
    for key in list(sys.modules):
        if key == "docker" or key.startswith("docker."):
            del sys.modules[key]

    import site
    from pathlib import Path

    for site_dir in site.getsitepackages():
        docker_init = Path(site_dir) / "docker" / "__init__.py"
        if not docker_init.is_file():
            continue
        spec = importlib.util.spec_from_file_location("docker", docker_init)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules["docker"] = module
        spec.loader.exec_module(module)
        return module

    return importlib.import_module("docker")


def _docker_list_payload(item: Any) -> Any:
    """Return list-API payload from docker-py models or plain dicts.

    docker-py ``Container`` stores the list response in ``_attrs`` while the
    ``attrs`` property fetches full inspect data (where ``State`` is a dict).
    """
    if isinstance(item, dict):
        return item
    list_attrs = getattr(item, "_attrs", None)
    if isinstance(list_attrs, dict):
        return list_attrs
    if hasattr(item, "attrs"):
        raw = item.attrs
        if isinstance(raw, dict):
            state = raw.get("State")
            if isinstance(state, dict):
                name = raw.get("Name")
                names = [name] if isinstance(name, str) else raw.get("Names", [])
                return {
                    "Id": raw.get("Id", ""),
                    "Names": names,
                    "State": state.get("Status", ""),
                    "Labels": (raw.get("Config") or {}).get("Labels") or {},
                }
            return raw
    return item


def create_engine_client(client: Any | None = None) -> EngineClient:
    """Create an EngineClient backed by docker-py."""
    docker = _load_docker_py()
    ImageNotFound = docker.errors.ImageNotFound
    try:
        docker_client = client if client is not None else docker.from_env()
    except Exception as e:
        raise RuntimeError(
            "Docker is not running or cannot be reached. Please ensure Docker Desktop is started "
            f"and you have permission to access the Docker socket/pipe.\nOriginal error: {e}"
        ) from e

    class _EngineClientImpl:
        async def list_containers(
            self, *, all: bool = False, filters: dict[str, list[str]] | None = None
        ) -> list[ContainerSummary]:
            docker_opts: dict[str, Any] = {"all": all}
            if filters is not None:
                docker_opts["filters"] = filters
            raw = await asyncio.to_thread(
                lambda: docker_client.containers.list(**docker_opts)
            )
            return [
                ContainerSummary.model_validate(_docker_list_payload(item)) for item in raw
            ]

        async def inspect(self, container_id: str) -> ContainerInspect:
            def _inspect() -> ContainerInspect:
                container = docker_client.containers.get(container_id)
                return ContainerInspect.model_validate(container.attrs)

            return await asyncio.to_thread(_inspect)

        async def stats(self, container_id: str) -> ContainerStats:
            def _stats() -> ContainerStats:
                container = docker_client.containers.get(container_id)
                data = container.stats(stream=False)
                return ContainerStats.model_validate(data)

            return await asyncio.to_thread(_stats)

        async def inspect_image(self, name_or_id: str) -> ImageInspect | None:
            def _inspect_image() -> ImageInspect | None:
                try:
                    image = docker_client.images.get(name_or_id)
                    return ImageInspect.model_validate(image.attrs)
                except ImageNotFound:
                    return None

            return await asyncio.to_thread(_inspect_image)

        async def list_images(
            self, *, filters: dict[str, list[str]] | None = None
        ) -> list[ImageSummary]:
            docker_opts: dict[str, Any] = {}
            if filters is not None:
                docker_opts["filters"] = filters
            raw = await asyncio.to_thread(
                lambda: docker_client.images.list(**docker_opts)
            )
            return [
                ImageSummary.model_validate(_docker_list_payload(item)) for item in raw
            ]

        async def pull_image(
            self, image: str, *, signal: Any | None = None
        ) -> AsyncIterator[str]:
            def sync_pull() -> Iterator[str]:
                stream = docker_client.images.pull(image, stream=True)
                for chunk in stream:
                    if isinstance(chunk, bytes):
                        line = chunk.decode("utf-8", errors="replace")
                    elif isinstance(chunk, str):
                        line = chunk
                    else:
                        line = json.dumps(chunk)
                    formatted = _format_pull_progress_line(line)
                    if formatted:
                        yield formatted

            async for line in aiter_in_thread(sync_pull):
                if signal is not None and getattr(signal, "is_set", lambda: False)():
                    return
                yield line

    return _EngineClientImpl()  # type: ignore[return-value]


def _format_pull_progress_line(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return line
    if data.get("error"):
        return str(data["error"])
    parts = [str(data.get(k, "")) for k in ("id", "status", "progress")]
    return " ".join(p for p in parts if p)


__all__ = ["create_engine_client"]

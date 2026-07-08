"""
Image validation: local docker-py first, registry fallback, in-memory cache.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from docker_mcp_server.services.docker.image_reference import parse_image_reference
from docker_mcp_server.services.docker.registry_client import (
    RegistryCheckResult,
    RegistryCheckStatusValues,
    RegistryClient,
    create_registry_client,
)
from docker_mcp_server.services.docker.types import EngineClient

ImageValidationStatus = Literal["valid", "invalid", "unknown"]
ImageValidationSource = Literal["local", "registry", "unavailable"]


@dataclass(frozen=True)
class ImageValidationResult:
    image: str
    status: ImageValidationStatus
    source: ImageValidationSource
    error: str | None = None
    suggestion: str | None = None


class ImageValidator:
    def __init__(
        self,
        engine_client: EngineClient,
        registry_client: RegistryClient,
        *,
        cache_ttl_ms: int = 60 * 60 * 1000,
        now: Any | None = None,
    ) -> None:
        self._engine = engine_client
        self._registry = registry_client
        self._cache: dict[str, tuple[float, ImageValidationResult]] = {}
        self._cache_ttl_ms = cache_ttl_ms
        self._now = now if now is not None else time.monotonic

    async def validate_image(
        self, image: str, *, signal: Any | None = None
    ) -> ImageValidationResult:
        try:
            parse_image_reference(image)
        except Exception as err:
            return ImageValidationResult(
                image=image,
                status="invalid",
                source="unavailable",
                error=str(err),
            )

        local = await self._engine.inspect_image(image)
        if local is not None:
            return ImageValidationResult(image=image, status="valid", source="local")

        now = self._now() * 1000
        if image in self._cache:
            expires_at, cached = self._cache[image]
            if now < expires_at:
                return cached

        registry_result = await self._registry.check_image_exists(image, signal=signal)
        result = self._registry_result_to_validation(registry_result)
        self._cache[image] = (now + self._cache_ttl_ms, result)
        return result

    async def validate_images(
        self, images: list[str], *, signal: Any | None = None
    ) -> list[ImageValidationResult]:
        unique = list(dict.fromkeys(images))
        by_image: dict[str, ImageValidationResult] = {}
        for img in unique:
            by_image[img] = await self.validate_image(img, signal=signal)
        return [by_image[img] for img in images]

    def _registry_result_to_validation(
        self, result: RegistryCheckResult
    ) -> ImageValidationResult:
        if result.status == RegistryCheckStatusValues.EXISTS:
            return ImageValidationResult(
                image=result.image, status="valid", source="registry"
            )
        if result.status == RegistryCheckStatusValues.MISSING:
            return ImageValidationResult(
                image=result.image,
                status="invalid",
                source="registry",
                error=result.error,
                suggestion=result.suggestion,
            )
        return ImageValidationResult(
            image=result.image,
            status="unknown",
            source="unavailable",
            error=result.error,
        )


def create_image_validator(
    engine_client: EngineClient,
    registry_client: RegistryClient | None = None,
    *,
    cache_ttl_ms: int = 60 * 60 * 1000,
) -> ImageValidator:
    return ImageValidator(
        engine_client,
        registry_client if registry_client is not None else create_registry_client(),
        cache_ttl_ms=cache_ttl_ms,
    )


def format_image_validation_error(
    results: list[ImageValidationResult], *, block_unknown: bool = False
) -> str | None:
    failures = [
        r
        for r in results
        if r.status == "invalid" or (block_unknown and r.status == "unknown")
    ]
    if not failures:
        return None
    lines: list[str] = []
    for f in failures:
        reason = f.error or "could not verify image"
        line = f"- {f.image}: {reason}"
        if f.suggestion:
            line += f". {f.suggestion}"
        lines.append(line)
    return "\n".join(lines)


def image_validation_warnings(results: list[ImageValidationResult]) -> list[str]:
    return [
        f"warning: could not verify Docker image '{r.image}'"
        + (f" ({r.error})" if r.error else "")
        for r in results
        if r.status == "unknown"
    ]


__all__ = [
    "ImageValidationResult",
    "ImageValidationSource",
    "ImageValidationStatus",
    "ImageValidator",
    "create_image_validator",
    "format_image_validation_error",
    "image_validation_warnings",
]

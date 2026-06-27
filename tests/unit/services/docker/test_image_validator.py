"""Parity tests for image_validator — mirrors src/services/docker/imageValidator.ts."""

from typing import Any

import pytest

from src.services.docker.image_validator import (
    ImageValidationResult,
    create_image_validator,
    format_image_validation_error,
)
from src.services.docker.registry_client import (
    RegistryCheckResult,
    RegistryCheckStatusValues,
)
from src.services.docker.types import ImageInspect


class FakeEngineClient:
    def __init__(self, local: dict[str, ImageInspect | None]) -> None:
        self.local = local

    async def inspect_image(self, name_or_id: str) -> ImageInspect | None:
        return self.local.get(name_or_id)

    async def list_images(self, **kwargs: Any) -> list[Any]:
        return []


class FakeRegistryClient:
    def __init__(self, results: dict[str, RegistryCheckResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    async def check_image_exists(self, image: str, **kwargs: Any) -> RegistryCheckResult:
        self.calls.append(image)
        return self.results.get(
            image,
            RegistryCheckResult(
                image=image,
                status=RegistryCheckStatusValues.UNKNOWN,
                registry="",
                repository="",
                reference="",
            ),
        )


@pytest.mark.asyncio
async def test_validator_prefers_local_image() -> None:
    engine = FakeEngineClient(
        {
            "nginx:1.27": ImageInspect.model_validate(
                {
                    "Id": "sha:abc",
                    "RepoTags": ["nginx:1.27"],
                    "Size": 1,
                    "Architecture": "amd64",
                    "Os": "linux",
                    "Created": "t",
                }
            )
        }
    )
    validator = create_image_validator(engine)
    result = await validator.validate_image("nginx:1.27")
    assert result.status == "valid"
    assert result.source == "local"


@pytest.mark.asyncio
async def test_validator_falls_back_to_registry() -> None:
    engine = FakeEngineClient({"nginx:1.27": None})
    registry = FakeRegistryClient(
        {
            "nginx:1.27": RegistryCheckResult(
                image="nginx:1.27",
                status=RegistryCheckStatusValues.EXISTS,
                registry="r",
                repository="r",
                reference="t",
            )
        }
    )
    validator = create_image_validator(engine, registry)
    result = await validator.validate_image("nginx:1.27")
    assert result.status == "valid"
    assert result.source == "registry"


@pytest.mark.asyncio
async def test_validator_caches_registry_result() -> None:
    engine = FakeEngineClient({"x": None})
    registry = FakeRegistryClient(
        {
            "x": RegistryCheckResult(
                image="x",
                status=RegistryCheckStatusValues.EXISTS,
                registry="r",
                repository="r",
                reference="t",
            )
        }
    )
    validator = create_image_validator(engine, registry)
    await validator.validate_image("x")
    await validator.validate_image("x")
    assert registry.calls == ["x"]


@pytest.mark.asyncio
async def test_validate_images_deduplicates() -> None:
    engine = FakeEngineClient(
        {
            "nginx": ImageInspect.model_validate(
                {
                    "Id": "sha:abc",
                    "RepoTags": ["nginx"],
                    "Size": 1,
                    "Architecture": "amd64",
                    "Os": "linux",
                    "Created": "t",
                }
            )
        }
    )
    validator = create_image_validator(engine)
    results = await validator.validate_images(["nginx", "nginx"])
    assert results[0].status == "valid"
    assert results[1].status == "valid"


def test_format_error_returns_none_when_all_valid() -> None:
    results = [
        ImageValidationResult(image="x", status="valid", source="local"),
    ]
    assert format_image_validation_error(results) is None


def test_format_error_includes_unknown_when_block_unknown() -> None:
    results = [
        ImageValidationResult(
            image="x", status="unknown", source="unavailable", error="timeout"
        ),
    ]
    error = format_image_validation_error(results, block_unknown=True)
    assert error is not None
    assert "x" in error
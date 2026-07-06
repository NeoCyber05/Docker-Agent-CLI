"""Parity tests for image_validation â€” mirrors src/tools/shared/imageValidation.ts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from docker_mcp_server.services.docker.image_validator import ImageValidationResult
from docker_mcp_server.tools.base import ToolContext
from docker_mcp_server.tools.shared.image_validation import validate_images_for_tool


class FakeValidator:
    def __init__(self, results: list[ImageValidationResult]) -> None:
        self.results = results
        self.called_with: list[str] = []

    async def validate_images(
        self, images: list[str], *, signal: Any | None = None
    ) -> list[ImageValidationResult]:
        self.called_with = images
        by_image = {r.image: r for r in self.results}
        return [by_image[img] for img in images]


def _ctx(validator: FakeValidator) -> ToolContext:
    return ToolContext(
        cwd="/tmp",
        state_store=object(),  # type: ignore[arg-type]
        docker_engine=object(),
        compose_runner=object(),  # type: ignore[arg-type]
        abort_signal=asyncio.Event(),
        image_validator=validator,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_validate_images_for_tool_deduplicates_images() -> None:
    validator = FakeValidator(
        [
            ImageValidationResult(image="nginx:1.27", status="valid", source="local"),
            ImageValidationResult(image="redis:7", status="valid", source="local"),
        ]
    )
    result = await validate_images_for_tool(
        ["nginx:1.27", "nginx:1.27", "redis:7"],
        _ctx(validator),
    )
    assert validator.called_with == ["nginx:1.27", "redis:7"]
    assert len(result.results) == 2
    assert result.results[0].image == "nginx:1.27"
    assert result.results[1].image == "redis:7"


@pytest.mark.asyncio
async def test_validate_images_for_tool_returns_error_for_invalid_images() -> None:
    validator = FakeValidator(
        [
            ImageValidationResult(
                image="missing:tag",
                status="invalid",
                source="registry",
                error="not found",
            )
        ]
    )
    result = await validate_images_for_tool(["missing:tag"], _ctx(validator))
    assert result.error is not None
    assert "missing:tag" in result.error


@pytest.mark.asyncio
async def test_validate_images_for_tool_returns_warnings_for_unknown_images() -> None:
    validator = FakeValidator(
        [
            ImageValidationResult(
                image="private/img:latest",
                status="unknown",
                source="unavailable",
                error="timeout",
            )
        ]
    )
    result = await validate_images_for_tool(["private/img:latest"], _ctx(validator))
    assert result.error is None
    assert len(result.warnings) == 1
    assert "private/img:latest" in result.warnings[0]


@pytest.mark.asyncio
async def test_validate_images_for_tool_blocks_unknown_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_AGENT_IMAGE_VALIDATION_UNKNOWN", "block")
    validator = FakeValidator(
        [
            ImageValidationResult(
                image="private/img:latest",
                status="unknown",
                source="unavailable",
            )
        ]
    )
    result = await validate_images_for_tool(["private/img:latest"], _ctx(validator))
    assert result.error is not None
    monkeypatch.delenv("DOCKER_AGENT_IMAGE_VALIDATION_UNKNOWN", raising=False)



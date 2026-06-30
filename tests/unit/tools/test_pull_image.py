"""Parity tests for pull_image."""

from __future__ import annotations

import asyncio

import pytest

from docker_agent.services.docker.image_validator import ImageValidationResult
from docker_agent.tools.base import ToolContext
from docker_agent.tools.pull_image import PullImageInput, pull_image
from tests.mocks.mock_compose_runner import MockComposeRunner
from tests.mocks.mock_docker_engine import MockDockerEngine
from tests.unit.tools.conftest import drain_with_progress


class FakeValidator:
    def __init__(self, result: ImageValidationResult) -> None:
        self.result = result
        self.called_with: str | None = None

    async def validate_image(self, image: str, *, signal=None) -> ImageValidationResult:
        self.called_with = image
        return self.result

    async def validate_images(self, images: list[str], *, signal=None):
        return [self.result]


def _ctx(validator: FakeValidator, engine: MockDockerEngine) -> ToolContext:
    return ToolContext(
        cwd="/tmp",
        state_store=object(),  # type: ignore[arg-type]
        docker_engine=engine,
        compose_runner=MockComposeRunner(),
        abort_signal=asyncio.Event(),
        image_validator=validator,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_pull_image_does_not_pull_invalid_registry_images() -> None:
    engine = MockDockerEngine()
    validator = FakeValidator(
        ImageValidationResult(
            image="postgres:99-alpine",
            status="invalid",
            source="registry",
            error="manifest not found",
            suggestion="postgres:17-alpine",
        )
    )

    _, result = await drain_with_progress(
        pull_image.call(PullImageInput(image="postgres:99-alpine"), _ctx(validator, engine))
    )

    assert result.ok is False
    assert result.status == "invalid"
    assert result.suggestion == "postgres:17-alpine"
    assert engine.pull_image_calls == []


@pytest.mark.asyncio
async def test_pull_image_pulls_valid_registry_images() -> None:
    engine = MockDockerEngine()
    engine.pull_image_lines = ["layer 1 complete", "done"]
    validator = FakeValidator(
        ImageValidationResult(
            image="nginx:1.27-alpine",
            status="valid",
            source="registry",
        )
    )

    progress, result = await drain_with_progress(
        pull_image.call(PullImageInput(image="nginx:1.27-alpine"), _ctx(validator, engine))
    )

    assert result.ok is True
    assert result.status == "valid"
    assert result.source == "pulled"
    assert len(engine.pull_image_calls) == 1
    assert engine.pull_image_calls[0][0] == "nginx:1.27-alpine"
    assert [item.msg for item in progress] == [
        "Validating nginx:1.27-alpine...",
        "Pulling nginx:1.27-alpine...",
        "layer 1 complete",
        "done",
    ]
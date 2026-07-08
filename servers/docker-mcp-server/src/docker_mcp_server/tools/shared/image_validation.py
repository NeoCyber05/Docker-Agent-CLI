"""Tool-level image validation wrapper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from docker_mcp_server.services.docker.image_validator import (
    ImageValidationResult,
    create_image_validator,
    format_image_validation_error,
    image_validation_warnings,
)
from docker_mcp_server.tools.base import ToolContext


@dataclass
class ToolImageValidationResult:
    results: list[ImageValidationResult]
    error: str | None
    warnings: list[str]


def _should_block_unknown_images() -> bool:
    return os.environ.get("DOCKER_AGENT_IMAGE_VALIDATION_UNKNOWN") == "block"


async def validate_images_for_tool(
    images: list[str], ctx: ToolContext
) -> ToolImageValidationResult:
    """Validate a deduplicated list of images for tool use."""
    validator = (
        ctx.image_validator
        if ctx.image_validator is not None
        else create_image_validator(ctx.docker_engine)
    )
    unique_images = list(dict.fromkeys(images))
    results = await validator.validate_images(
        unique_images, signal=ctx.abort_signal
    )
    return ToolImageValidationResult(
        results=results,
        error=format_image_validation_error(
            results, block_unknown=_should_block_unknown_images()
        ),
        warnings=image_validation_warnings(results),
    )


__all__ = ["ToolImageValidationResult", "validate_images_for_tool"]

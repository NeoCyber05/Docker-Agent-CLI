"""pull_image tool.

Parity: ``src/tools/pullImage.ts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel

from src.services.docker.image_validator import create_image_validator
from src.tool import ToolContext, ToolDone, ToolProgress


class PullImageInput(BaseModel):
    image: str


class PullImageResult(BaseModel):
    ok: bool
    status: Literal["valid", "invalid", "unknown"]
    source: Literal["local", "registry", "pulled", "unavailable"] | None = None
    error: str | None = None
    suggestion: str | None = None


class _PullImageTool:
    name = "pull_image"
    description = (
        "Validate a Docker image reference and pre-pull it when it exists in a registry "
        "but is not local."
    )
    input_schema = PullImageInput
    category = "escape-hatch"

    def needs_permission(self, _input: PullImageInput) -> bool:
        return True

    async def call(
        self, input: PullImageInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        validator = (
            ctx.image_validator
            if ctx.image_validator is not None
            else create_image_validator(ctx.docker_engine)
        )
        yield ToolProgress(msg=f"Validating {input.image}...")
        validation = await validator.validate_image(
            input.image, signal=ctx.abort_signal
        )

        if validation.status == "invalid":
            yield ToolDone(
                PullImageResult(
                    ok=False,
                    status="invalid",
                    source=validation.source,
                    error=validation.error,
                    suggestion=validation.suggestion,
                )
            )
            return

        if validation.status == "unknown":
            yield ToolDone(
                PullImageResult(
                    ok=True,
                    status="unknown",
                    source=validation.source,
                    error=validation.error,
                )
            )
            return

        if validation.source == "registry":
            pull_image_fn = getattr(ctx.docker_engine, "pull_image", None)
            if pull_image_fn is None:
                yield ToolDone(
                    PullImageResult(
                        ok=False,
                        status="valid",
                        source="registry",
                        error="Docker engine does not support image pulling",
                    )
                )
                return
            yield ToolProgress(msg=f"Pulling {input.image}...")
            async for line in pull_image_fn(input.image, signal=ctx.abort_signal):
                yield ToolProgress(msg=line)
            yield ToolDone(PullImageResult(ok=True, status="valid", source="pulled"))
            return

        yield ToolDone(
            PullImageResult(
                ok=True,
                status="valid",
                source=validation.source,
            )
        )


pull_image = _PullImageTool()

__all__ = ["PullImageInput", "PullImageResult", "pull_image"]
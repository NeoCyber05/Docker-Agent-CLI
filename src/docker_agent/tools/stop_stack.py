"""stop_stack tool — stop managed stack containers without removing them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from docker_agent.config import stack_state_yaml_path
from docker_agent.tool import ToolContext, ToolDone, ToolProgress


class StopStackInput(BaseModel):
    stack_name: str = Field(alias="stackName")
    services: list[str] | None = None

    model_config = {"populate_by_name": True}

    @field_validator("services")
    @classmethod
    def _normalize_services(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [service.strip() for service in value if service.strip()]
        return normalized or None


class StopStackResult(BaseModel):
    ok: bool
    exit_code: int = Field(alias="exitCode")
    stopped_services: list[str] = Field(default_factory=list, alias="stoppedServices")
    reason: str | None = None
    message: str | None = None

    model_config = {"populate_by_name": True}


class _StopStackTool:
    name = "stop_stack"
    description = (
        "Stop running containers for a stack managed by docker-agent without removing them "
        "(docker compose stop). Stack YAML and container definitions are preserved; use "
        "apply_stack to start again. Optionally limit to specific service names."
    )
    input_schema = StopStackInput
    category = "high-level"

    def needs_permission(self, _input: StopStackInput) -> bool:
        return True

    async def call(
        self, input: StopStackInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yaml_path = stack_state_yaml_path(input.stack_name, ctx.cwd)
        if not Path(yaml_path).exists():
            message = (
                f"No stack file for {input.stack_name}; this stack is not managed by "
                "docker-agent."
            )
            yield ToolProgress(msg=message)
            yield ToolDone(
                StopStackResult(
                    ok=False,
                    exit_code=1,
                    reason="stack_file_not_found",
                    message=message,
                )
            )
            return

        target = (
            f"{input.stack_name} ({', '.join(input.services)})"
            if input.services
            else input.stack_name
        )
        yield ToolProgress(msg=f"Compose stop for {target}...")
        bound = ctx.compose_runner.for_stack(input.stack_name, yaml_path)
        async for line in bound.stop(services=input.services):
            if line.strip():
                yield ToolProgress(msg=line.rstrip())
        exit_code = getattr(bound, "last_exit_code", 0)
        yield ToolDone(
            StopStackResult(
                ok=exit_code == 0,
                exit_code=exit_code,
                stopped_services=input.services or [],
            )
        )


stop_stack = _StopStackTool()

__all__ = ["StopStackInput", "StopStackResult", "stop_stack"]

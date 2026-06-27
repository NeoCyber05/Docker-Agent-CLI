"""validate_spec tool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from src.tool import ToolContext, ToolDone, ToolProgress
from src.tools.shared.config_files import (
    StagedConfigFile,
    detect_missing_config_files,
    stage_config_files,
)
from src.tools.shared.image_validation import validate_images_for_tool
from src.tools.shared.spec_schemas import StackDraft
from src.tools.shared.translator import prepare_stack_draft
from src.types.stack import ServiceSpec

SpecIssueCode = Literal[
    "invalid_image", "invalid_config_path", "missing_config_file", "invalid_spec"
]


@dataclass
class SpecIssue:
    code: SpecIssueCode
    path: str
    message: str


@dataclass
class ValidateSpecResult:
    valid: bool
    issues: list[SpecIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _ValidateSpecInput(BaseModel):
    stack_name: str | None = Field(default=None, alias="stackName")
    intent: str | None = None
    services: list[Any]
    config_files: dict[str, str] | None = Field(default=None, alias="configFiles")


async def validate_spec_input(
    input: dict[str, Any],
    ctx: ToolContext,
) -> ValidateSpecResult:
    """Validate images and config file bindings for prepared services."""
    issues: list[SpecIssue] = []
    services: dict[str, ServiceSpec] = input["services"]
    config_files: dict[str, str] | None = input.get("config_files")

    image_validation = await validate_images_for_tool(
        [service.image for service in services.values()],
        ctx,
    )
    if image_validation.error:
        issues.append(
            SpecIssue(
                code="invalid_image",
                path="services",
                message=image_validation.error,
            )
        )

    staged = stage_config_files(ctx.cwd, services, config_files)
    if not staged.get("ok"):
        issues.append(
            SpecIssue(
                code="invalid_config_path",
                path="configFiles",
                message=str(staged.get("error", "unknown")),
            )
        )
    else:
        staged_files = cast(list[StagedConfigFile], staged.get("staged", []))
        missing = detect_missing_config_files(
            services,
            {f.path for f in staged_files},
            ctx.cwd,
        )
        for item in missing:
            issues.append(
                SpecIssue(
                    code="missing_config_file",
                    path=f"services.{item['service']}.volumes",
                    message=(
                        f"Missing content for bind-mounted config file "
                        f"'{item['path']}'."
                    ),
                )
            )

    return ValidateSpecResult(
        valid=len(issues) == 0,
        issues=issues,
        warnings=image_validation.warnings,
    )


class _ValidateSpecTool:
    name = "validate_spec"
    description = (
        "Validate a draft stack service spec: Docker images, bind-mounted "
        "config paths, and missing config file content."
    )
    input_schema = _ValidateSpecInput
    category = "read-only"

    def needs_permission(self, _input: Any) -> bool:
        return False

    async def call(
        self, input: _ValidateSpecInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg="Validating stack spec...")
        draft = StackDraft.model_validate(
            {
                "stackName": input.stack_name or "validate-temp-stack",
                "intent": input.intent or "validation only",
                "services": input.services,
                "configFiles": input.config_files,
            }
        )
        prep = await prepare_stack_draft(draft, ctx)
        if not prep.ok:
            yield ToolDone(
                ValidateSpecResult(
                    valid=False,
                    issues=[
                        SpecIssue(
                            code="invalid_spec",
                            path="services",
                            message=prep.error or "unknown",
                        )
                    ],
                    warnings=[],
                )
            )
            return
        assert prep.prepared is not None
        spec_input: dict[str, Any] = {"services": prep.prepared.services}
        if input.config_files is not None:
            spec_input["config_files"] = input.config_files
        yield ToolDone(await validate_spec_input(spec_input, ctx))


validate_spec = _ValidateSpecTool()

__all__ = [
    "SpecIssue",
    "ValidateSpecResult",
    "validate_spec",
    "validate_spec_input",
]
"""validate_spec tool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docker_agent.tools.base import ToolContext, ToolDone, ToolProgress
from docker_agent.tools.shared.config_files import (
    StagedConfigFile,
    detect_missing_config_files,
    stage_config_files,
)
from docker_agent.tools.shared.image_validation import validate_images_for_tool
from docker_agent.tools.shared.network_guard import check_network_references
from docker_agent.tools.shared.spec_schemas import (
    HybridServiceIntent,
    NetworkIntent,
    StackDraft,
    VolumeIntent,
    format_validation_error,
)
from docker_agent.tools.shared.volume_guard import check_volume_references
from docker_agent.tools.shared.translator import prepare_stack_draft
from docker_agent.types.stack import ServiceSpec

SpecIssueCode = Literal[
    "invalid_image",
    "invalid_config_path",
    "missing_config_file",
    "invalid_spec",
    "undeclared_network",
    "undeclared_volume",
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
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    stack_name: str | None = Field(default=None, alias="stackName")
    intent: str | None = None
    network_name: str | None = Field(default=None, alias="networkName")
    networks: list[NetworkIntent] | None = None
    volumes: list[VolumeIntent] | None = None
    services: list[HybridServiceIntent]
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


def _stack_draft_payload(input: _ValidateSpecInput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stackName": input.stack_name or "validate-temp-stack",
        "intent": input.intent or "validation only",
        "services": input.services,
    }
    if input.network_name is not None:
        payload["networkName"] = input.network_name
    if input.networks:
        payload["networks"] = [
            n.model_dump(by_alias=True, exclude_none=True) for n in input.networks
        ]
    if input.volumes:
        payload["volumes"] = [
            v.model_dump(by_alias=True, exclude_none=True) for v in input.volumes
        ]
    if input.config_files is not None:
        payload["configFiles"] = input.config_files
    return payload


class _ValidateSpecTool:
    name = "validate_spec"
    description = (
        "Validate a draft stack service spec: Docker images, bind-mounted "
        "config paths, missing config file content, and top-level network/volume "
        "declarations."
    )
    input_schema = _ValidateSpecInput
    category = "read-only"

    def needs_permission(self, _input: Any) -> bool:
        return False

    async def call(
        self, input: _ValidateSpecInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg="Validating stack spec...")
        try:
            draft = StackDraft.model_validate(_stack_draft_payload(input))
        except ValidationError as err:
            yield ToolDone(
                ValidateSpecResult(
                    valid=False,
                    issues=[
                        SpecIssue(
                            code="invalid_spec",
                            path="services",
                            message=format_validation_error(err),
                        )
                    ],
                    warnings=[],
                )
            )
            return
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
        prepared = prep.prepared

        network_issues = check_network_references(
            prepared.services, prepared.networks
        )
        if network_issues:
            yield ToolDone(
                ValidateSpecResult(
                    valid=False,
                    issues=[
                        SpecIssue(
                            code="undeclared_network",
                            path=f"services.{issue.service}.networks",
                            message=issue.message,
                        )
                        for issue in network_issues
                    ],
                    warnings=[],
                )
            )
            return

        volume_ref_issues = check_volume_references(
            prepared.services, prepared.volumes
        )
        if volume_ref_issues:
            yield ToolDone(
                ValidateSpecResult(
                    valid=False,
                    issues=[
                        SpecIssue(
                            code="undeclared_volume",
                            path=f"services.{issue.service}.volumeMounts",
                            message=issue.message,
                        )
                        for issue in volume_ref_issues
                    ],
                    warnings=[],
                )
            )
            return

        spec_input: dict[str, Any] = {"services": prepared.services}
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
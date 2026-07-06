"""validate_spec tool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress
from docker_mcp_server.tools.shared.app_source_guard import check_app_source_artifacts
from docker_mcp_server.tools.shared.config_files import (
    StagedConfigFile,
    detect_missing_config_files,
    stage_config_files,
)
from docker_mcp_server.tools.shared.image_validation import validate_images_for_tool
from docker_mcp_server.tools.shared.port_conflicts import (
    CheckPortConflictResult,
    check_port_conflicts,
)
from docker_mcp_server.tools.shared.spec_schemas import (
    HybridServiceIntent,
    NetworkIntent,
    StackDraft,
    VolumeIntent,
    format_validation_error,
)
from docker_mcp_server.tools.shared.translator import prepare_stack_draft
from docker_mcp_server.types.stack import ServiceSpec

VALIDATE_SPEC_SCOPE = (
    "draft_preflight: StackDraft structure, Docker image availability, "
    "config file bindings, application source artifacts, and published port conflicts."
)

SpecIssueCode = Literal[
    "invalid_image",
    "invalid_config_path",
    "missing_config_file",
    "missing_app_source",
    "invalid_spec",
    "invalid_port",
    "port_conflict",
    "port_check_unavailable",
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
    scope: str = VALIDATE_SPEC_SCOPE


class _ValidateSpecInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    stack_name: str = Field(alias="stackName")
    intent: str
    network_name: str | None = Field(default=None, alias="networkName")
    networks: list[NetworkIntent] | None = None
    volumes: list[VolumeIntent] | None = None
    services: list[HybridServiceIntent]
    config_files: dict[str, str] | None = Field(default=None, alias="configFiles")


async def validate_spec_input(
    input: dict[str, Any],
    ctx: ToolContext,
) -> ValidateSpecResult:
    """Validate image availability and LLM-provided artifacts for prepared services."""
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

    staged_files: list[StagedConfigFile] = []
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

    for issue in check_app_source_artifacts(services, {f.path for f in staged_files}):
        issues.append(
            SpecIssue(
                code="missing_app_source",
                path=f"services.{issue.service}.command",
                message=issue.message,
            )
        )

    return ValidateSpecResult(
        valid=len(issues) == 0,
        issues=issues,
        warnings=image_validation.warnings,
    )


def _stack_draft_payload(input: _ValidateSpecInput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stackName": input.stack_name,
        "intent": input.intent,
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


def _port_check_issues(port_check: CheckPortConflictResult) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    for item in port_check.invalid:
        service = item.get("service", "*")
        value = item.get("value", "ports")
        issues.append(
            SpecIssue(
                code="invalid_port",
                path=f"services.{service}.ports",
                message=f"Invalid port mapping '{value}': {item.get('message', 'invalid')}",
            )
        )
    for conflict in port_check.conflicts:
        issues.append(
            SpecIssue(
                code="port_conflict",
                path=f"services.{conflict.service}.ports",
                message=(
                    f"Port {conflict.host_ip}:{conflict.host_port}/{conflict.protocol} "
                    f"for service '{conflict.service}' conflicts with "
                    f"{conflict.conflicts_with} ({conflict.source})."
                ),
            )
        )
    if port_check.docker_error is not None:
        issues.append(
            SpecIssue(
                code="port_check_unavailable",
                path="services",
                message=port_check.docker_error.get("message", "port check unavailable"),
            )
        )
    return issues


class _ValidateSpecTool:
    name = "validate_spec"
    description = (
        "Required preflight for a complete draft stack intent before plan_stack. "
        "valid=True means the draft schema is well-formed, required artifacts are "
        "present, Docker images can be resolved, and published host ports do not "
        "conflict with the draft or currently running containers. Does not approve "
        "deployment policy or replace plan_stack's mandatory gate."
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

        spec_input: dict[str, Any] = {"services": prepared.services}
        if input.config_files is not None:
            spec_input["config_files"] = input.config_files
        result = await validate_spec_input(spec_input, ctx)
        port_check = await check_port_conflicts(draft.stack_name, prepared.services, ctx)
        port_issues = _port_check_issues(port_check)
        if port_issues:
            result.issues.extend(port_issues)
            result.valid = False
        yield ToolDone(result)


validate_spec = _ValidateSpecTool()

__all__ = [
    "VALIDATE_SPEC_SCOPE",
    "SpecIssue",
    "ValidateSpecResult",
    "validate_spec",
    "validate_spec_input",
]


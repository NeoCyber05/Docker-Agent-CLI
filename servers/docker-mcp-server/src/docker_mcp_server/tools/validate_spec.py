"""validate_spec tool and shared preflight gate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress
from docker_mcp_server.tools.resolve_dependency import (
    ResolveDependencyResult,
    resolve_dependencies,
)
from docker_mcp_server.tools.shared.app_source_guard import (
    AppSourceIssue,
    check_app_source_artifacts,
)
from docker_mcp_server.tools.shared.config_files import (
    StagedConfigFile,
    detect_missing_config_files,
    stage_config_files,
)
from docker_mcp_server.tools.shared.db_port_guard import DbPortExposureIssue, check_db_port_exposure
from docker_mcp_server.tools.shared.image_validation import validate_images_for_tool
from docker_mcp_server.tools.shared.network_guard import NetworkIssue, check_network_references
from docker_mcp_server.tools.shared.port_conflicts import (
    CheckPortConflictResult,
    check_port_conflicts,
)
from docker_mcp_server.tools.shared.resource_limits import ResourceLimitIssue, check_resource_limits
from docker_mcp_server.tools.shared.spec_schemas import (
    HybridServiceIntent,
    NetworkIntent,
    StackDraft,
    VolumeIntent,
    format_validation_error,
)
from docker_mcp_server.tools.shared.translator import PreparedStack, prepare_stack_draft
from docker_mcp_server.tools.shared.volume_guard import VolumeIssue, check_volume_references, check_volume_safety
from docker_mcp_server.types.stack import ServiceSpec

PREFLIGHT_CHECKS = [
    "image",
    "config",
    "app_source",
    "port",
    "dependency",
    "resource",
    "db_port",
    "volume",
    "network",
]

VALIDATE_SPEC_SCOPE = (
    "draft_preflight: StackDraft structure, Docker image availability, "
    "config file bindings, application source artifacts, published port conflicts, "
    "dependency order, resource limits, database port exposure, volume safety/references, "
    "and network references."
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
    "invalid_dependency",
    "resource_limit",
    "db_port_exposed",
    "unsafe_volume",
    "undeclared_volume",
    "undeclared_network",
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


@dataclass
class PreflightReport:
    ok: bool
    progress: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    issues: list[SpecIssue] = field(default_factory=list)
    app_source_issues: list[AppSourceIssue] | None = None
    dependency: ResolveDependencyResult | None = None
    port_check: CheckPortConflictResult | None = None
    resource_issues: list[ResourceLimitIssue] | None = None
    db_port_issues: list[DbPortExposureIssue] | None = None
    volume_issues: list[VolumeIssue] | None = None
    network_issues: list[NetworkIssue] | None = None


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


def _dependency_issues(dependency: ResolveDependencyResult) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    for item in dependency.missing:
        issues.append(
            SpecIssue(
                code="invalid_dependency",
                path=f"services.{item.service}.depends_on",
                message=(
                    f"service '{item.service}' depends on missing service "
                    f"'{item.dependency}'"
                ),
            )
        )
    for cycle in dependency.cycles:
        issues.append(
            SpecIssue(
                code="invalid_dependency",
                path="services",
                message=f"dependency cycle detected: {' -> '.join(cycle)}",
            )
        )
    return issues


def _resource_issues_to_spec(issues: list[ResourceLimitIssue]) -> list[SpecIssue]:
    return [
        SpecIssue(code="resource_limit", path=issue.path, message=issue.message)
        for issue in issues
    ]


def _db_port_issues_to_spec(issues: list[DbPortExposureIssue]) -> list[SpecIssue]:
    return [
        SpecIssue(
            code="db_port_exposed",
            path=f"services.{issue.service}.ports",
            message=issue.message,
        )
        for issue in issues
    ]


def _volume_issues_to_spec(issues: list[VolumeIssue], *, code: SpecIssueCode) -> list[SpecIssue]:
    return [
        SpecIssue(
            code=code,
            path=f"services.{issue.service}.volumes",
            message=issue.message,
        )
        for issue in issues
    ]


def _network_issues_to_spec(issues: list[NetworkIssue]) -> list[SpecIssue]:
    return [
        SpecIssue(
            code="undeclared_network",
            path=f"services.{issue.service}.networks",
            message=issue.message,
        )
        for issue in issues
    ]


def _app_source_issues_to_spec(issues: list[AppSourceIssue]) -> list[SpecIssue]:
    return [
        SpecIssue(
            code="missing_app_source",
            path=f"services.{issue.service}.command",
            message=issue.message,
        )
        for issue in issues
    ]


def _record_check(report: PreflightReport, name: str) -> None:
    report.checks_run.append(name)


def _finalize_failure(
    report: PreflightReport,
    *,
    reason: str,
    issues: list[SpecIssue] | None = None,
) -> PreflightReport:
    report.ok = False
    report.failure_reason = reason
    if issues:
        report.issues.extend(issues)
    return report


async def run_preflight(
    *,
    stack_name: str,
    prepared: PreparedStack,
    config_files: dict[str, str] | None,
    ctx: ToolContext,
    stop_at_first: bool = True,
) -> PreflightReport:
    """Run all draft preflight guards in a fixed order."""
    report = PreflightReport(ok=True)
    report.progress.append("Validating service spec...")

    config_paths = set(config_files.keys()) if config_files else set()
    app_source_issues = check_app_source_artifacts(prepared.services, config_paths)
    _record_check(report, "app_source")
    if app_source_issues:
        report.app_source_issues = app_source_issues
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="missing_app_source",
                issues=_app_source_issues_to_spec(app_source_issues),
            )
        report.issues.extend(_app_source_issues_to_spec(app_source_issues))

    spec_input: dict[str, Any] = {"services": prepared.services}
    if config_files is not None:
        spec_input["config_files"] = config_files
    spec_check = await validate_spec_input(spec_input, ctx)
    _record_check(report, "image")
    _record_check(report, "config")
    report.warnings.extend(spec_check.warnings)
    if not spec_check.valid:
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="invalid_spec",
                issues=list(spec_check.issues),
            )
        report.issues.extend(spec_check.issues)

    dependency = resolve_dependencies(prepared.services)
    _record_check(report, "dependency")
    if not dependency.valid:
        report.dependency = dependency
        dep_issues = _dependency_issues(dependency)
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="invalid_dependency",
                issues=dep_issues,
            )
        report.issues.extend(dep_issues)

    port_check = await check_port_conflicts(stack_name, prepared.services, ctx)
    _record_check(report, "port")
    port_issues = _port_check_issues(port_check)
    if port_issues:
        report.port_check = port_check
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="port_conflict",
                issues=port_issues,
            )
        report.issues.extend(port_issues)

    resource_issues = check_resource_limits(prepared.services)
    _record_check(report, "resource")
    if resource_issues:
        report.resource_issues = resource_issues
        res_issues = _resource_issues_to_spec(resource_issues)
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="resource_limit",
                issues=res_issues,
            )
        report.issues.extend(res_issues)

    db_port_issues = check_db_port_exposure(prepared.services)
    _record_check(report, "db_port")
    if db_port_issues:
        report.db_port_issues = db_port_issues
        db_issues = _db_port_issues_to_spec(db_port_issues)
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="db_port_exposed",
                issues=db_issues,
            )
        report.issues.extend(db_issues)

    volume_issues = check_volume_safety(ctx.cwd, prepared.services)
    _record_check(report, "volume")
    if volume_issues:
        report.volume_issues = volume_issues
        vol_issues = _volume_issues_to_spec(volume_issues, code="unsafe_volume")
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="unsafe_volume",
                issues=vol_issues,
            )
        report.issues.extend(vol_issues)

    volume_ref_issues = check_volume_references(prepared.services, prepared.volumes)
    if volume_ref_issues:
        report.volume_issues = volume_ref_issues
        vol_ref_spec = _volume_issues_to_spec(volume_ref_issues, code="undeclared_volume")
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="undeclared_volume",
                issues=vol_ref_spec,
            )
        report.issues.extend(vol_ref_spec)

    network_issues = check_network_references(prepared.services, prepared.networks)
    _record_check(report, "network")
    if network_issues:
        report.network_issues = network_issues
        net_issues = _network_issues_to_spec(network_issues)
        if stop_at_first:
            return _finalize_failure(
                report,
                reason="undeclared_network",
                issues=net_issues,
            )
        report.issues.extend(net_issues)

    if report.issues:
        report.ok = False
        if report.failure_reason is None:
            report.failure_reason = "invalid_spec"
    return report


def preflight_report_to_artifact(report: PreflightReport) -> dict[str, Any]:
    status = "Preflight passed" if report.ok else "Preflight blocked"
    checks = ", ".join(report.checks_run or PREFLIGHT_CHECKS)
    content = (
        f"{status}\n"
        f"Checks: {checks}\n"
        f"Warnings: {len(report.warnings)}\n"
        f"Issues: {len(report.issues)}"
    )
    return {
        "kind": "validation",
        "label": "Preflight report",
        "language": "text",
        "content": content,
    }


def preflight_report_to_validation_details(report: PreflightReport) -> dict[str, Any]:
    return {
        "status": "passed" if report.ok else "blocked",
        "checks": list(report.checks_run or PREFLIGHT_CHECKS),
        "warnings": len(report.warnings),
        "issues": len(report.issues),
    }


def preflight_report_to_validate_result(report: PreflightReport) -> ValidateSpecResult:
    return ValidateSpecResult(
        valid=report.ok,
        issues=list(report.issues),
        warnings=list(report.warnings),
    )


class _ValidateSpecTool:
    name = "validate_spec"
    description = (
        "Optional diagnostic preflight for a complete draft stack intent. "
        "valid=True means the draft schema is well-formed, required artifacts are "
        "present, Docker images can be resolved, published host ports do not conflict, "
        "dependencies are valid, resource limits are acceptable, database ports are "
        "not exposed, volumes are safe and declared, and network references are valid. "
        "Does not approve deployment policy; docker.deploy_stack re-runs the same "
        "full preflight gate internally."
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
        report = await run_preflight(
            stack_name=draft.stack_name,
            prepared=prep.prepared,
            config_files=input.config_files,
            ctx=ctx,
            stop_at_first=False,
        )
        for warning in report.warnings:
            yield ToolProgress(msg=warning)
        yield ToolDone(preflight_report_to_validate_result(report))


validate_spec = _ValidateSpecTool()

__all__ = [
    "PREFLIGHT_CHECKS",
    "VALIDATE_SPEC_SCOPE",
    "PreflightReport",
    "SpecIssue",
    "ValidateSpecResult",
    "preflight_report_to_artifact",
    "preflight_report_to_validate_result",
    "preflight_report_to_validation_details",
    "run_preflight",
    "validate_spec",
    "validate_spec_input",
]

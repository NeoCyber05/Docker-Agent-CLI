"""resolve_dependency tool.

Parity: ``src/tools/resolveDependency.ts``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.tool import ToolContext, ToolDone, ToolProgress
from src.tools.shared.spec_schemas import HybridServiceIntent, StackDraft
from src.tools.shared.translator import prepare_stack_draft
from src.types.stack import ServiceSpec

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)
_STACK_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


class ResolveDependencyInput(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str | None = Field(default=None, alias="stackName")
    intent: str | None = None
    services: list[HybridServiceIntent]

    @field_validator("stack_name")
    @classmethod
    def _validate_stack_name(cls, value: str | None) -> str | None:
        if value is not None and not _STACK_NAME_PATTERN.match(value):
            raise ValueError("stackName must match ^[a-z][a-z0-9_-]{0,62}$")
        return value


class MissingDependency(BaseModel):
    model_config = _MODEL_CONFIG

    service: str
    dependency: str


class ResolveDependencyResult(BaseModel):
    model_config = _MODEL_CONFIG

    valid: bool
    order: list[str]
    missing: list[MissingDependency]
    cycles: list[list[str]]


def _dependency_names(service: ServiceSpec) -> list[str]:
    depends_on = service.depends_on
    if not depends_on:
        return []
    if isinstance(depends_on, list):
        return depends_on
    return list(depends_on.keys())


def resolve_dependencies(
    services: dict[str, ServiceSpec],
) -> ResolveDependencyResult:
    """Topological sort with missing-dependency and cycle detection."""
    missing: list[MissingDependency] = []
    cycles: list[list[str]] = []
    cycle_keys: set[str] = set()
    order: list[str] = []
    state: dict[str, str] = dict.fromkeys(services, "unvisited")

    def visit(service_name: str, path: list[str]) -> None:
        current = state.get(service_name)
        if current == "visited":
            return
        if current == "visiting":
            cycle_start = path.index(service_name)
            if cycle_start >= 0:
                cycle = [*path[cycle_start:], service_name]
                key = "->".join(cycle)
                if key not in cycle_keys:
                    cycle_keys.add(key)
                    cycles.append(cycle)
            return

        state[service_name] = "visiting"
        spec = services.get(service_name) or ServiceSpec(image="unknown")
        deps = sorted(_dependency_names(spec))
        for dep in deps:
            if dep not in services:
                edge = MissingDependency(service=service_name, dependency=dep)
                if edge not in missing:
                    missing.append(edge)
                continue
            visit(dep, [*path, service_name])
        state[service_name] = "visited"
        order.append(service_name)

    for name in sorted(services):
        if state.get(name) == "unvisited":
            visit(name, [])

    return ResolveDependencyResult(
        valid=len(missing) == 0 and len(cycles) == 0,
        order=order,
        missing=missing,
        cycles=cycles,
    )


class ResolveDependencyTool:
    name = "resolve_dependency"
    description = (
        "Validate declared service dependencies, report missing references or "
        "cycles, and return dependency-first startup order."
    )
    input_schema = ResolveDependencyInput
    category = "read-only"

    def needs_permission(self, _input: ResolveDependencyInput) -> bool:
        return False

    async def call(
        self, input: ResolveDependencyInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg="Resolving service dependencies...")
        draft = StackDraft.model_validate(
            {
                "stackName": input.stack_name or "validate-temp-stack",
                "intent": input.intent or "validation only",
                "services": input.services,
            }
        )
        prep = await prepare_stack_draft(draft, ctx)
        if not prep.ok:
            yield ToolDone(
                ResolveDependencyResult(
                    valid=False,
                    order=[],
                    missing=[
                        MissingDependency(
                            service="*", dependency=prep.error or "error"
                        )
                    ],
                    cycles=[],
                )
            )
            return
        yield ToolDone(resolve_dependencies(prep.prepared.services))  # type: ignore[union-attr]


resolve_dependency = ResolveDependencyTool()

__all__ = [
    "MissingDependency",
    "ResolveDependencyInput",
    "ResolveDependencyResult",
    "ResolveDependencyTool",
    "resolve_dependencies",
    "resolve_dependency",
]
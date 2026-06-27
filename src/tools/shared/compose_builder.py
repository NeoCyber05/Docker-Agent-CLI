"""Compose definition builder and YAML helpers.

Parity: ``src/tools/shared/composeBuilder.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from src.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


@dataclass
class PlanInput:
    stack_name: str
    intent: str
    services: dict[str, ServiceSpec]
    networks: dict[str, Any] | None = None
    volumes: dict[str, Any] | None = None


@dataclass
class BuildStackResult:
    definition: StackDefinition
    scale_overrides: dict[str, int]


def build_stack_definition(
    input: PlanInput,
    previous: StackDefinition | None,
    provider: str,
    generated_by: str,
) -> BuildStackResult:
    """Build a ``StackDefinition`` with x-docker-agent metadata."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    scale_overrides: dict[str, int] = {}

    for name, spec in input.services.items():
        if spec.scale is not None and spec.scale > 1:
            scale_overrides[name] = spec.scale

    prev_meta = previous.x_docker_agent if previous is not None else None
    meta = DockerAgentMeta.model_validate(
        {
            "name": input.stack_name,
            "createdAt": prev_meta.created_at if prev_meta is not None else now,
            "lastApplied": prev_meta.last_applied if prev_meta is not None else None,
            "intent": input.intent,
            "provider": provider,
            "generatedBy": generated_by,
            "envFileSources": (
                prev_meta.env_file_sources if prev_meta is not None else {}
            ),
        }
    )

    definition = StackDefinition.model_validate(
        {
            "x-docker-agent": meta.model_dump(by_alias=True),
            "services": {
                name: spec.model_dump(by_alias=True, exclude_none=True)
                for name, spec in input.services.items()
            },
            **({"networks": input.networks} if input.networks else {}),
            **({"volumes": input.volumes} if input.volumes else {}),
        }
    )
    return BuildStackResult(definition=definition, scale_overrides=scale_overrides)


def stack_to_yaml(definition: StackDefinition) -> str:
    """Serialize a stack definition to YAML."""
    dumped: str = yaml.safe_dump(
        definition.model_dump(by_alias=True, exclude_none=True),
        sort_keys=False,
    )
    return dumped


def compose_yaml_for_preview(compose_yaml: str) -> str:
    """Strip internal x-docker-agent metadata for user-facing compose previews."""
    try:
        parsed = yaml.safe_load(compose_yaml)
        if not isinstance(parsed, dict):
            return compose_yaml
        rest = {k: v for k, v in parsed.items() if k != "x-docker-agent"}
        dumped: str = yaml.safe_dump(rest, sort_keys=False)
        return dumped.rstrip()
    except Exception:
        return compose_yaml


__all__ = [
    "BuildStackResult",
    "PlanInput",
    "build_stack_definition",
    "compose_yaml_for_preview",
    "stack_to_yaml",
]
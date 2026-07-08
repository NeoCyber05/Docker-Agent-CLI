"""YAML round-trip validation for stack definitions.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from pydantic import ValidationError

from docker_mcp_server.types.stack import StackDefinition


@dataclass
class YamlRoundTripResult:
    ok: bool
    error: str | None = None


def _format_validation_error(err: ValidationError) -> str:
    parts = []
    for issue in err.errors():
        loc = "/".join(str(x) for x in issue["loc"]) or "<root>"
        parts.append(f"{loc}: {issue['msg']}")
    return "; ".join(parts)


def validate_yaml_round_trip(yaml_text: str) -> YamlRoundTripResult:
    """Parse YAML and validate against ``StackDefinition``."""
    if not yaml_text.strip():
        return YamlRoundTripResult(ok=False, error="empty YAML")

    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as err:
        return YamlRoundTripResult(
            ok=False,
            error=f"YAML parse failed: {err}",
        )

    try:
        StackDefinition.model_validate(parsed)
    except ValidationError as err:
        return YamlRoundTripResult(
            ok=False,
            error=f"schema validation failed: {_format_validation_error(err)}",
        )

    return YamlRoundTripResult(ok=True)


__all__ = ["YamlRoundTripResult", "validate_yaml_round_trip"]

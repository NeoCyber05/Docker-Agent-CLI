"""Parity tests for yaml_round_trip â€” mirrors src/tools/shared/__tests__/yamlRoundTrip.test.ts."""

import yaml

from docker_mcp_server.tools.shared.yaml_round_trip import validate_yaml_round_trip
from docker_mcp_server.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _valid_def() -> StackDefinition:
    return StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name="test",
            created_at="2026-01-01T00:00:00.000Z",
            last_applied=None,
            intent="test",
            provider="gemini",
            generated_by="test",
            env_file_sources={},
        ),
        services={"web": ServiceSpec(image="nginx:1.27-alpine", ports=["8080:80"])},
    )


def test_passes_for_valid_yaml_round_trip() -> None:
    yaml_text = yaml.safe_dump(_valid_def().model_dump(by_alias=True), sort_keys=False)
    result = validate_yaml_round_trip(yaml_text)
    assert result.ok is True
    assert result.error is None


def test_fails_for_malformed_yaml() -> None:
    result = validate_yaml_round_trip("services: [unclosed")
    assert result.ok is False
    assert result.error is not None
    assert "parse" in result.error.lower()


def test_fails_for_valid_yaml_that_does_not_match_schema() -> None:
    result = validate_yaml_round_trip("foo: bar\n")
    assert result.ok is False
    assert result.error is not None
    assert "schema" in result.error


def test_fails_for_empty_string() -> None:
    result = validate_yaml_round_trip("")
    assert result.ok is False



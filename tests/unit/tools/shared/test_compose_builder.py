"""Parity tests for compose_builder — mirrors src/tools/shared/composeBuilder.test.ts."""

import yaml

from docker_agent.tools.shared.compose_builder import (
    PlanInput,
    build_stack_definition,
    compose_yaml_for_preview,
    stack_to_yaml,
)
from docker_agent.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition


def _previous() -> StackDefinition:
    return StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name="redis-cache",
            created_at="2026-06-23T06:11:12.361Z",
            last_applied="2026-06-23T06:13:01.634Z",
            intent="old",
            provider="unknown",
            generated_by="unknown",
            env_file_sources={},
        ),
        services={"redis": ServiceSpec(image="redis:7")},
    )


def test_build_stack_definition_preserves_created_at_and_scale_overrides() -> None:
    services = {
        "web": ServiceSpec(image="nginx:1.27-alpine", scale=2),
        "cache": ServiceSpec(image="redis:7"),
    }
    result = build_stack_definition(
        PlanInput(stack_name="demo", intent="deploy", services=services),
        _previous(),
        "gemini",
        "test",
    )
    assert result.definition.x_docker_agent.created_at == "2026-06-23T06:11:12.361Z"
    assert result.definition.x_docker_agent.last_applied == "2026-06-23T06:13:01.634Z"
    assert result.definition.x_docker_agent.provider == "gemini"
    assert result.scale_overrides == {"web": 2}


def test_stack_to_yaml_round_trips() -> None:
    definition = build_stack_definition(
        PlanInput(
            stack_name="test",
            intent="test",
            services={"web": ServiceSpec(image="nginx:1.27-alpine", ports=["8080:80"])},
        ),
        None,
        "gemini",
        "test",
    ).definition
    yaml_text = stack_to_yaml(definition)
    parsed = yaml.safe_load(yaml_text)
    assert parsed["x-docker-agent"]["name"] == "test"
    assert parsed["services"]["web"]["image"] == "nginx:1.27-alpine"


def test_compose_yaml_for_preview_removes_x_docker_agent_metadata() -> None:
    yaml_text = "\n".join(
        [
            "x-docker-agent:",
            "  name: redis-cache",
            "  createdAt: 2026-06-23T06:11:12.361Z",
            "  lastApplied: 2026-06-23T06:13:01.634Z",
            '  intent: "Adjust redis-cache"',
            "  provider: unknown",
            "  generatedBy: unknown",
            "  envFileSources: {}",
            "services:",
            "  redis:",
            "    image: redis:7",
        ]
    )
    preview = compose_yaml_for_preview(yaml_text)
    assert "x-docker-agent" not in preview
    assert "redis-cache" not in preview
    assert "createdAt" not in preview
    assert "services:" in preview
    assert "image: redis:7" in preview


def test_compose_yaml_for_preview_returns_original_on_parse_failure() -> None:
    malformed = "services: [unclosed"
    assert compose_yaml_for_preview(malformed) == malformed


def test_build_stack_definition_includes_networks_and_volumes() -> None:
    services = {
        "web": ServiceSpec(image="nginx:1.27-alpine", networks=["frontend"]),
        "db": ServiceSpec(image="postgres:16-alpine", networks=["backend"]),
    }
    result = build_stack_definition(
        PlanInput(
            stack_name="demo",
            intent="deploy",
            services=services,
            networks={
                "default": {},
                "frontend": {},
                "backend": {"internal": True},
            },
            volumes={
                "pgdata": {"driver": "local"},
            },
        ),
        None,
        "gemini",
        "test",
    )
    assert result.definition.networks == {
        "default": {},
        "frontend": {},
        "backend": {"internal": True},
    }
    assert result.definition.volumes == {"pgdata": {"driver": "local"}}

    yaml_text = stack_to_yaml(result.definition)
    parsed = yaml.safe_load(yaml_text)
    assert parsed["networks"]["backend"]["internal"] is True
    assert parsed["volumes"]["pgdata"]["driver"] == "local"
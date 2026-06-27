"""Parity tests for slash dispatch — mirrors src/__tests__/slashDispatch.test.ts."""

from __future__ import annotations

from docker_agent.slash_dispatch import (
    SlashDispatchContext,
    destroy_stack_prompt,
    dispatch_secrets_list,
    dispatch_stacks,
    dispatch_yaml,
    format_stacks_table,
    is_destroy_all_prompt,
    parse_direct_destroy_stack,
)
from docker_agent.state.state_store import StateStore
from docker_agent.types.stack import DockerAgentMeta, EnvFileSource, ServiceSpec, StackDefinition


def make_def(
    name: str,
    *,
    service_extras: dict[str, object] | None = None,
) -> StackDefinition:
    service = ServiceSpec(
        image="nginx:1.27-alpine",
        environment={"POSTGRES_PASSWORD": "super-secret", "PORT": "8080"},
        **(service_extras or {}),
    )
    return StackDefinition(
        x_docker_agent=DockerAgentMeta(
            name=name,
            createdAt="2026-05-26T00:00:00Z",
            lastApplied="2026-06-01T12:00:00Z",
            intent="test",
            provider="gemini",
            generatedBy="test",
            envFileSources={
                "web": EnvFileSource(
                    generated=True,
                    path=".docker-agent/secrets/web.env",
                    addedKeys=["API_TOKEN"],
                )
            },
        ),
        services={"web": service},
    )


def test_format_stacks_table_shows_empty_message_when_no_stacks() -> None:
    assert "Managed stacks" in format_stacks_table([])
    assert "No stacks defined" in format_stacks_table([])


def test_dispatch_stacks_renders_markdown_table(tmp_project) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    ctx = SlashDispatchContext(cwd=str(tmp_project), state_store=store)
    store.write("webapp", make_def("webapp"))
    text = dispatch_stacks(ctx)
    assert "| Name | Services | Last applied |" in text
    assert "| webapp | 1 |" in text


def test_dispatch_yaml_redacts_secret_environment_values(tmp_project) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    ctx = SlashDispatchContext(cwd=str(tmp_project), state_store=store)
    store.write("webapp", make_def("webapp"))
    result = dispatch_yaml("webapp", ctx)
    assert result["ok"] is True
    if not result["ok"]:
        return
    assert "POSTGRES_PASSWORD" in result["text"]
    assert "***" in result["text"]
    assert "super-secret" not in result["text"]
    assert "PORT" in result["text"] and "8080" in result["text"]


def test_dispatch_yaml_returns_error_for_missing_stack(tmp_project) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    ctx = SlashDispatchContext(cwd=str(tmp_project), state_store=store)
    result = dispatch_yaml("missing", ctx)
    assert result == {"ok": False, "error": "stack missing not found"}


def test_dispatch_secrets_list_returns_tracked_secret_key_names_only(tmp_project) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    ctx = SlashDispatchContext(cwd=str(tmp_project), state_store=store)
    store.write("webapp", make_def("webapp"))
    result = dispatch_secrets_list("webapp", ctx)
    assert result["ok"] is True
    if not result["ok"]:
        return
    assert "API_TOKEN" in result["text"]
    assert "POSTGRES_PASSWORD" in result["text"]
    assert "super-secret" not in result["text"]


def test_destroy_stack_prompt_and_parse_direct_destroy_stack_round_trip() -> None:
    assert destroy_stack_prompt("webapp") == "Destroy stack webapp"
    assert destroy_stack_prompt("webapp", True) == "Destroy stack webapp with volumes"
    assert parse_direct_destroy_stack("Destroy stack webapp") == {
        "stack_name": "webapp",
        "remove_volumes": False,
    }
    assert parse_direct_destroy_stack("destroy webapp with volumes") == {
        "stack_name": "webapp",
        "remove_volumes": True,
    }
    assert parse_direct_destroy_stack("destroy all stacks") is None
    assert is_destroy_all_prompt("Destroy all stacks") is True
    assert is_destroy_all_prompt("destroy all stacks") is True


def test_dispatch_secrets_list_reports_when_no_keys_are_tracked(tmp_project) -> None:
    store = StateStore(str(tmp_project / ".docker-agent"))
    ctx = SlashDispatchContext(cwd=str(tmp_project), state_store=store)
    definition = make_def("plain")
    definition.x_docker_agent.env_file_sources = {}
    definition.services["web"] = ServiceSpec(
        image="nginx:1.27-alpine",
        environment={"PORT": "8080"},
    )
    store.write("plain", definition)
    result = dispatch_secrets_list("plain", ctx)
    assert result["ok"] is True
    if not result["ok"]:
        return
    assert "No secret keys tracked" in result["text"]
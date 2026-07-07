from __future__ import annotations

from infra_agent.core.prompt_builder import build_system_prompt


def test_base_prompt_is_domain_agnostic() -> None:
    prompt = build_system_prompt("stacks: {}\n")

    # Generic, domain-neutral control-plane guidance lives in the core prompt.
    assert "infrastructure automation assistant" in prompt
    assert "two-phase flow" in prompt
    assert "namespaced set" in prompt
    # Docker-specific guidance must NOT be hardcoded in the core prompt anymore;
    # it is contributed by the Docker plugin's capabilities instead.
    assert "docker.deploy_stack" not in prompt
    assert "catalogId" not in prompt


def test_prompt_injects_plugin_instructions() -> None:
    instructions = "## Widgets\n\nUse `widget.apply` for everything."
    prompt = build_system_prompt("stacks: {}\n", plugin_instructions=instructions)

    assert "## Widgets" in prompt
    assert "Use `widget.apply` for everything." in prompt


def test_prompt_without_plugins_notes_none_connected() -> None:
    prompt = build_system_prompt("stacks: {}\n")

    assert "No infrastructure plugins are currently connected." in prompt


def test_prompt_injects_state_summary() -> None:
    prompt = build_system_prompt("stacks:\n  web: running\n")

    assert "web: running" in prompt


def test_prompt_defaults_empty_state_summary() -> None:
    prompt = build_system_prompt("")

    assert "(none)" in prompt

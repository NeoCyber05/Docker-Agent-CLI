from __future__ import annotations

from infra_agent.slash.dispatch import (
    SlashDispatchContext,
    destroy_stack_prompt,
    dispatch_stacks,
    dispatch_yaml,
    is_destroy_all_prompt,
    parse_direct_destroy_stack,
    parse_direct_stop_stack,
    stop_stack_prompt,
)


def test_dispatch_stacks_is_mcp_routed_guidance(tmp_project) -> None:
    text = dispatch_stacks(SlashDispatchContext(cwd=str(tmp_project)))
    assert "List managed Docker stacks" in text


def test_dispatch_yaml_is_mcp_routed_guidance(tmp_project) -> None:
    result = dispatch_yaml("webapp", SlashDispatchContext(cwd=str(tmp_project)))
    assert result == {"ok": True, "text": "Use the agent prompt `Show YAML for stack webapp`."}


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


def test_stop_stack_prompt_and_parse_direct_stop_stack_round_trip() -> None:
    assert stop_stack_prompt("webapp") == "Stop stack webapp"
    assert stop_stack_prompt("webapp", ["api", "web"]) == "Stop stack webapp services api, web"
    assert parse_direct_stop_stack("Stop stack webapp") == {"stack_name": "webapp"}
    assert parse_direct_stop_stack("stop webapp") == {"stack_name": "webapp"}
    assert parse_direct_stop_stack("Stop stack webapp services api, web") == {
        "stack_name": "webapp",
        "services": ["api", "web"],
    }
    assert parse_direct_stop_stack("stop webapp services api web") == {
        "stack_name": "webapp",
        "services": ["api", "web"],
    }

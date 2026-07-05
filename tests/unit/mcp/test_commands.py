from __future__ import annotations

from docker_agent.mcp.commands import CommandSpec, match_command


def test_match_command_uses_plugin_metadata_for_typed_destroy() -> None:
    spec = CommandSpec(
        pattern=r"^destroy (?P<stack_name>\S+) with volumes$",
        tool="docker.destroy_stack",
        confirmation="typed",
        args={"stack_name": "$stack_name", "remove_volumes": True},
        phrase_template="DESTROY {stack_name}",
        reason_template="Destroy {stack_name} and delete its volumes.",
    )

    match = match_command("destroy web with volumes", [spec])

    assert match is not None
    assert match.tool == "docker.destroy_stack"
    assert match.input == {"stack_name": "web", "remove_volumes": True}
    assert match.confirmation == "typed"
    assert match.phrase == "DESTROY web"
    assert match.reason == "Destroy web and delete its volumes."


def test_match_command_splits_services_from_metadata() -> None:
    spec = CommandSpec(
        pattern=r"^stop (?P<stack_name>\S+)(?: services (?P<services>.+))?$",
        tool="docker.stop_stack",
        confirmation="permission",
        args={"stack_name": "$stack_name"},
        split_args={"services": "services"},
    )

    match = match_command("stop web services api, worker db", [spec])

    assert match is not None
    assert match.input == {
        "stack_name": "web",
        "services": ["api", "worker", "db"],
    }

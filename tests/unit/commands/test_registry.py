"""Parity tests for command registry."""

from __future__ import annotations

from infra_agent.commands.registry import Command, CommandRegistry, create_default_registry
from infra_agent.slash.commands import SLASH_COMMANDS


def test_register_and_get_all() -> None:
    registry = CommandRegistry()
    command = Command(id="test", title="/test", description="Test command")
    registry.register(command)
    commands = registry.get_all()
    assert len(commands) == 1
    assert commands[0].id == "test"


def test_register_upserts_by_id() -> None:
    registry = CommandRegistry()
    registry.register(Command(id="test", title="/test", description="First"))
    registry.register(Command(id="test", title="/test", description="Second"))
    commands = registry.get_all()
    assert len(commands) == 1
    assert commands[0].description == "Second"


def test_find_by_id() -> None:
    registry = CommandRegistry()
    registry.register(Command(id="help", title="/help", description="Help"))
    assert registry.find_by_id("help") is not None
    assert registry.find_by_id("help").title == "/help"
    assert registry.find_by_id("missing") is None


def test_find_by_shortcut() -> None:
    registry = CommandRegistry()
    registry.register(
        Command(
            id="details",
            title="Details",
            description="Open tool details",
            shortcut="ctrl+o",
        )
    )
    assert registry.find_by_shortcut("ctrl+o") is not None
    assert registry.find_by_shortcut("ctrl+p") is None


def test_create_default_registry_uses_slash_catalog() -> None:
    registry = create_default_registry()
    commands = registry.get_all()
    assert len(commands) == len(SLASH_COMMANDS)
    ids = {command.id for command in commands}
    assert {"help", "model", "stacks", "connect"}.issubset(ids)
    help_command = registry.find_by_id("help")
    assert help_command is not None
    assert help_command.insert_text == "/help"

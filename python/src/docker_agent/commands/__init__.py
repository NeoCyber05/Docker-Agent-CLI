"""Command palette registry."""

from docker_agent.commands.registry import Command, CommandRegistry, create_default_registry

__all__ = ["Command", "CommandRegistry", "create_default_registry"]
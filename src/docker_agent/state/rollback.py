"""Rollback decision logic.

Parity: ``src/state/rollback.ts:1-103``.
"""

from typing import Any, Literal

import yaml

from docker_agent.state.state_store import StateStore
from docker_agent.types.stack import StackDefinition


class KnownGood:
    """Result of ``capture_known_good``."""

    def __init__(
        self,
        *,
        previous: StackDefinition | None,
        existed_expected: bool,
        recoverable: bool,
        previous_yaml: str | None = None,
    ) -> None:
        self.previous = previous
        self.existed_expected = existed_expected
        self.recoverable = recoverable
        self.previous_yaml = previous_yaml


class RollbackPlan:
    """Discriminated rollback plan."""

    def __init__(
        self,
        *,
        strategy: Literal["restore_previous", "teardown_partial", "none"],
        stack_name: str,
        compose_yaml: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.strategy = strategy
        self.stack_name = stack_name
        self.compose_yaml = compose_yaml
        self.reason = reason


def capture_known_good(stack_name: str, ctx: dict[str, Any]) -> KnownGood:
    """Determine what prior state can be used for rollback."""
    store: StateStore = ctx["state_store"]

    live = store.read(stack_name)
    if live is not None:
        return KnownGood(
            previous=live,
            existed_expected=True,
            recoverable=True,
            previous_yaml=yaml.safe_dump(
                live.model_dump(by_alias=True, exclude_none=True),
                sort_keys=False,
            ),
        )

    archived = store.read_archive(stack_name)
    if archived is not None:
        return KnownGood(
            previous=archived,
            existed_expected=True,
            recoverable=True,
            previous_yaml=yaml.safe_dump(
                archived.model_dump(by_alias=True, exclude_none=True),
                sort_keys=False,
            ),
        )

    if store.has_archive_marker(stack_name):
        return KnownGood(
            previous=None, existed_expected=True, recoverable=False
        )

    return KnownGood(
        previous=None, existed_expected=False, recoverable=False
    )


def plan_rollback(known: KnownGood, stack_name: str) -> RollbackPlan:
    """Choose rollback strategy from the captured known-good state."""
    if known.existed_expected and known.recoverable:
        return RollbackPlan(
            strategy="restore_previous",
            stack_name=stack_name,
            compose_yaml=known.previous_yaml or "",
        )
    if not known.existed_expected:
        return RollbackPlan(
            strategy="teardown_partial", stack_name=stack_name
        )
    return RollbackPlan(
        strategy="none",
        stack_name=stack_name,
        reason="no recoverable prior state (live file and archive both unavailable)",
    )


__all__ = ["KnownGood", "RollbackPlan", "capture_known_good", "plan_rollback"]
"""Interaction phase state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, TypedDict

InteractionPhase = Literal[
    "idle", "running", "awaiting_input", "cancelling", "queue_paused"
]


@dataclass
class InteractionState:
    phase: InteractionPhase = "idle"
    queue: list[str] = field(default_factory=list)
    current: str | None = None
    turn_id: int = 0


class SubmitAction(TypedDict):
    type: Literal["submit"]
    text: str


class TurnStartedAction(TypedDict):
    type: Literal["turn_started"]


class TurnEndedAction(TypedDict, total=False):
    type: Literal["turn_ended"]
    cancelled: bool
    error: bool


class AwaitingInputAction(TypedDict):
    type: Literal["awaiting_input"]


class InputResolvedAction(TypedDict):
    type: Literal["input_resolved"]


class CancelCurrentAction(TypedDict):
    type: Literal["cancel_current"]


class ResumeQueueAction(TypedDict):
    type: Literal["resume_queue"]


class RemoveQueuedAction(TypedDict):
    type: Literal["remove_queued"]
    index: int


class ClearQueueAction(TypedDict):
    type: Literal["clear_queue"]


class ResetAction(TypedDict):
    type: Literal["reset"]


InteractionAction = (
    SubmitAction
    | TurnStartedAction
    | TurnEndedAction
    | AwaitingInputAction
    | InputResolvedAction
    | CancelCurrentAction
    | ResumeQueueAction
    | RemoveQueuedAction
    | ClearQueueAction
    | ResetAction
)


def interaction_reducer(
    state: InteractionState, action: InteractionAction
) -> InteractionState:
    match action["type"]:
        case "reset":
            return InteractionState(
                phase="idle",
                queue=[],
                current=None,
                turn_id=state.turn_id + 1,
            )
        case "submit":
            if state.phase in {"idle", "queue_paused"}:
                return replace(
                    state,
                    phase="running",
                    current=action["text"],
                    turn_id=state.turn_id + 1,
                )
            return replace(state, queue=[*state.queue, action["text"]])
        case "turn_started":
            return replace(state, phase="running")
        case "turn_ended":
            cancelled = action.get("cancelled", False)
            error = action.get("error", False)
            if cancelled or error or state.phase == "cancelling":
                return replace(state, phase="queue_paused", current=None)
            if state.queue:
                next_prompt, *rest = state.queue
                return replace(
                    state,
                    phase="running",
                    current=next_prompt,
                    queue=rest,
                    turn_id=state.turn_id + 1,
                )
            return replace(state, phase="idle", current=None)
        case "awaiting_input":
            return replace(state, phase="awaiting_input")
        case "input_resolved":
            return replace(state, phase="running")
        case "cancel_current":
            if state.phase in {"running", "awaiting_input"}:
                return replace(state, phase="cancelling")
            return state
        case "resume_queue":
            if state.queue:
                next_prompt, *rest = state.queue
                return replace(
                    state,
                    phase="running",
                    current=next_prompt,
                    queue=rest,
                    turn_id=state.turn_id + 1,
                )
            return replace(state, phase="idle")
        case "remove_queued":
            index = action["index"]
            if index < 0 or index >= len(state.queue):
                return state
            next_queue = list(state.queue)
            next_queue.pop(index)
            return replace(state, queue=next_queue)
        case "clear_queue":
            return replace(state, queue=[])
        case _:
            return state


__all__ = [
    "InteractionAction",
    "InteractionPhase",
    "InteractionState",
    "interaction_reducer",
]
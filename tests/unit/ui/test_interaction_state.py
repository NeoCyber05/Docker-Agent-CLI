"""Parity tests for interaction_state â€” mirrors src/ui/__tests__/interactionState.test.ts."""

from __future__ import annotations

from infra_agent.ui.interaction_state import InteractionState, interaction_reducer


def make_state(**overrides: object) -> InteractionState:
    state = InteractionState()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_starts_turn_immediately_when_idle() -> None:
    next_state = interaction_reducer(make_state(), {"type": "submit", "text": "deploy"})
    assert next_state.phase == "running"
    assert next_state.current == "deploy"
    assert next_state.queue == []


def test_queues_submit_when_running() -> None:
    state = make_state(phase="running", current="deploy")
    state = interaction_reducer(state, {"type": "submit", "text": "status"})
    assert state.phase == "running"
    assert state.current == "deploy"
    assert state.queue == ["status"]


def test_runs_next_queued_turn_on_turn_ended() -> None:
    state = make_state(phase="running", current="deploy", queue=["status", "logs"])
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.phase == "running"
    assert state.current == "status"
    assert state.queue == ["logs"]


def test_goes_idle_when_turn_ends_with_empty_queue() -> None:
    state = make_state(phase="running", current="deploy", queue=[])
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.phase == "idle"
    assert state.current is None


def test_pauses_queue_after_cancel() -> None:
    state = make_state(phase="running", current="deploy", queue=["status"])
    state = interaction_reducer(state, {"type": "cancel_current"})
    assert state.phase == "cancelling"
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.phase == "queue_paused"
    assert state.queue == ["status"]


def test_pauses_queue_after_turn_error() -> None:
    state = make_state(phase="running", current="deploy", queue=["status"])
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": True})
    assert state.phase == "queue_paused"
    assert state.queue == ["status"]


def test_resumes_queue_and_dequeues_next() -> None:
    state = make_state(phase="queue_paused", current=None, queue=["status", "logs"])
    state = interaction_reducer(state, {"type": "resume_queue"})
    assert state.phase == "running"
    assert state.current == "status"
    assert state.queue == ["logs"]


def test_resumes_to_idle_when_queue_empty() -> None:
    state = make_state(phase="queue_paused", queue=[])
    state = interaction_reducer(state, {"type": "resume_queue"})
    assert state.phase == "idle"


def test_remove_queued_removes_by_index() -> None:
    state = make_state(phase="running", current="deploy", queue=["a", "b", "c"])
    state = interaction_reducer(state, {"type": "remove_queued", "index": 1})
    assert state.queue == ["a", "c"]


def test_ignores_invalid_queue_index() -> None:
    state = make_state(phase="running", current="deploy", queue=["a", "b"])
    assert interaction_reducer(state, {"type": "remove_queued", "index": -1}).queue == ["a", "b"]
    assert interaction_reducer(state, {"type": "remove_queued", "index": 2}).queue == ["a", "b"]


def test_clear_queue_empties_queue() -> None:
    state = make_state(phase="running", current="deploy", queue=["a", "b"])
    state = interaction_reducer(state, {"type": "clear_queue"})
    assert state.queue == []


def test_awaiting_input_sets_phase() -> None:
    state = make_state(phase="running", current="deploy")
    state = interaction_reducer(state, {"type": "awaiting_input"})
    assert state.phase == "awaiting_input"


def test_input_resolved_returns_to_running() -> None:
    state = make_state(phase="awaiting_input", current="deploy")
    state = interaction_reducer(state, {"type": "input_resolved"})
    assert state.phase == "running"


def test_new_turn_after_abort_starts_fresh() -> None:
    state = make_state(phase="queue_paused", queue=[])
    state = interaction_reducer(state, {"type": "submit", "text": "new"})
    assert state.phase == "running"
    assert state.current == "new"


def test_maintains_fifo_ordering_across_multiple_queued_submits() -> None:
    state = make_state(phase="running", current="first")
    state = interaction_reducer(state, {"type": "submit", "text": "second"})
    state = interaction_reducer(state, {"type": "submit", "text": "third"})
    assert state.queue == ["second", "third"]
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.current == "second"
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.current == "third"
    state = interaction_reducer(state, {"type": "turn_ended", "cancelled": False, "error": False})
    assert state.phase == "idle"

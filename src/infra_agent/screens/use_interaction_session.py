"""Async interaction session driver.

Parity: ``src/screens/useInteractionSession.ts``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from infra_agent.query_engine import QueryEngine
from infra_agent.types.events import (
    ActionReview,
    AssistantText,
    Error,
    LoopEvent,
    PermissionRequest,
    RollbackResult,
    RollbackStarted,
    SecretsInputRequest,
    ToolCall,
    ToolProgress,
    ToolResult,
    TypedConfirmRequest,
    Usage,
)
from infra_agent.types.message import Message
from infra_agent.types.permissions import PermissionResponse
from infra_agent.ui.activity import (
    ActivityAction,
    ActivityItem,
    ActivityState,
    activity_reducer,
    project_messages_to_activities,
)
from infra_agent.ui.interaction_state import (
    InteractionAction,
    InteractionPhase,
    InteractionState,
    interaction_reducer,
)


@dataclass
class InteractionSession:
    engine: QueryEngine
    interaction: InteractionState = field(default_factory=InteractionState)
    activity_state: ActivityState = field(default_factory=ActivityState)
    pending_event: LoopEvent | None = field(default=None, init=False)
    _pending_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _started_turn_id: int = field(default=-1, init=False)

    def __post_init__(self) -> None:
        snapshot = self.engine.get_activity_snapshot()
        if snapshot is not None:
            items = list(snapshot)
        else:
            items = project_messages_to_activities(self.engine.get_messages())
        self.activity_state = ActivityState(items=items, active_tool_activity_id=None)

    @property
    def phase(self) -> InteractionPhase:
        return self.interaction.phase

    @property
    def queue(self) -> list[str]:
        return self.interaction.queue

    @property
    def activities(self) -> list[ActivityItem]:
        return self.activity_state.items

    @property
    def active_tool_activity_id(self) -> str | None:
        return self.activity_state.active_tool_activity_id

    def submit(self, text: str) -> None:
        self._dispatch_interaction({"type": "submit", "text": text})

    def cancel_current(self) -> None:
        self.engine.abort()
        self._dispatch_interaction({"type": "cancel_current"})
        self.dispatch_activity({"type": "tool_cancelled"})
        self.pending_event = None

    def respond(self, request_id: str, answer: PermissionResponse) -> None:
        self.engine.respond_to(request_id, answer)
        self._dispatch_interaction({"type": "input_resolved"})
        self.pending_event = None

    def resume_queue(self) -> None:
        self._dispatch_interaction({"type": "resume_queue"})

    def remove_queued(self, index: int) -> None:
        self._dispatch_interaction({"type": "remove_queued", "index": index})

    def clear_queue(self) -> None:
        self._dispatch_interaction({"type": "clear_queue"})

    def reset(self) -> None:
        self.engine.reset()
        self.pending_event = None
        self._started_turn_id = -1
        self._dispatch_interaction({"type": "reset"})
        self.dispatch_activity({"type": "reset"})

    def dispatch_activity(self, action: ActivityAction) -> None:
        self.activity_state = activity_reducer(self.activity_state, action)

    def replace_activities(self, messages: list[Message]) -> None:
        snapshot = self.engine.get_activity_snapshot()
        items = (
            snapshot
            if snapshot is not None
            else project_messages_to_activities(messages)
        )
        self.dispatch_activity(
            {
                "type": "replace",
                "items": items,
            }
        )

    def _dispatch_interaction(self, action: InteractionAction) -> None:
        self.interaction = interaction_reducer(self.interaction, action)

    async def run_turn(self, text: str) -> None:
        self.dispatch_activity({"type": "user_text", "text": text})
        turn_errored = False
        try:
            async for ev in self.engine.query(text):
                if isinstance(ev, AssistantText):
                    self.dispatch_activity({"type": "assistant_text", "delta": ev.delta})
                    await asyncio.sleep(0)
                elif isinstance(ev, ToolCall):
                    self.dispatch_activity(
                        {"type": "tool_call", "name": ev.name, "input": ev.input}
                    )
                    await asyncio.sleep(0)
                elif isinstance(ev, ToolProgress):
                    self.dispatch_activity({"type": "tool_progress", "msg": ev.msg})
                    await asyncio.sleep(0)
                elif isinstance(ev, ToolResult):
                    self.dispatch_activity(
                        {
                            "type": "tool_result",
                            "name": ev.name,
                            "output": ev.output,
                        }
                    )
                    await asyncio.sleep(0)
                elif isinstance(ev, Error):
                    turn_errored = True
                    self.dispatch_activity(
                        {
                            "type": "tool_error",
                            "name": "active",
                            "error": str(ev.error),
                        }
                    )
                    self.dispatch_activity({"type": "error", "error": ev.error})
                elif isinstance(ev, Usage):
                    self.dispatch_activity(
                        {
                            "type": "usage",
                            "input_tokens": ev.input_tokens,
                            "output_tokens": ev.output_tokens,
                        }
                    )
                elif isinstance(ev, RollbackStarted):
                    self.dispatch_activity(
                        {
                            "type": "rollback_started",
                            "stack_name": ev.stack_name,
                            "reason": ev.reason,
                            "detail": ev.detail,
                        }
                    )
                elif isinstance(ev, RollbackResult):
                    self.dispatch_activity(
                        {
                            "type": "rollback_result",
                            "stack_name": ev.stack_name,
                            "ok": ev.ok,
                            "restored": ev.restored,
                            "detail": ev.detail,
                        }
                    )
                elif isinstance(ev, ActionReview):
                    self.dispatch_activity(
                        {
                            "type": "action_review_ready",
                            "request_id": ev.id,
                            "tool": ev.tool,
                            "title": ev.title,
                            "summary": ev.summary,
                            "artifacts": ev.artifacts,
                            "auto_generated_secrets": ev.secrets,
                            "config_files": ev.config_files,
                        }
                    )
                    self._dispatch_interaction({"type": "awaiting_input"})
                    self.pending_event = ev
                elif isinstance(
                    ev,
                    (
                        PermissionRequest,
                        TypedConfirmRequest,
                        SecretsInputRequest,
                    ),
                ):
                    self._dispatch_interaction({"type": "awaiting_input"})
                    self.pending_event = ev
        except Exception as err:  # noqa: BLE001
            self.dispatch_activity({"type": "error", "error": err})
            self._dispatch_interaction({"type": "turn_ended", "error": True})
            return

        if turn_errored:
            ended: InteractionAction = {"type": "turn_ended", "error": True}
        else:
            ended = {"type": "turn_ended"}
        self._dispatch_interaction(ended)

    async def run_loop(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            if (
                self.interaction.phase == "running"
                and self.interaction.current is not None
                and self.interaction.turn_id != self._started_turn_id
            ):
                self._started_turn_id = self.interaction.turn_id
                await self.run_turn(self.interaction.current)


__all__ = ["InteractionSession"]





"""Reusable query engine orchestrating a backend turn."""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import secrets
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter

from infra_agent.agent import BackendQueryParams, create_backend
from infra_agent.config import is_valid_provider
from infra_agent.core.iteration_limits import MAX_ITERATIONS
from infra_agent.core.loop_context import ActionReviewPayload
from infra_agent.services.api.types import Provider
from infra_agent.state.logger import LogEntry, StructuredLogger
from infra_agent.state.session_store import (
    SessionRecord,
    SessionStore,
    session_cwd_mismatch_warning,
)
from infra_agent.types.events import (
    ActionReview,
    AssistantText,
    Error,
    IterationStart,
    LoopEvent,
    PermissionRequest,
    RollbackResult,
    RollbackStarted,
    ToolCall,
    ToolProgress,
    ToolResult,
    Usage,
)
from infra_agent.types.message import Message, UserMessage
from infra_agent.types.permissions import PermissionResponse, PermissionResponseAdapter
from infra_agent.ui.activity import (
    ActivityItem,
    deserialize_activity_items,
    serialize_activity_items,
)
from infra_agent.utils.async_queue import AsyncQueue

_MessageListAdapter: TypeAdapter[list[Message]] = TypeAdapter(list[Message])
_LoopEventAdapter: TypeAdapter[LoopEvent] = TypeAdapter(LoopEvent)


def _nanoid() -> str:
    return secrets.token_urlsafe(16)


class _QueryLoopContext:
    """LoopContext implementation passed to the backend."""

    def __init__(
        self,
        *,
        cwd: str,
        abort_signal: asyncio.Event,
        session_id: str,
        provider_name: str,
        model: str | None,
        request_permission: Callable[..., Awaitable[PermissionResponse]],
        request_confirm: Callable[..., Awaitable[PermissionResponse]],
        request_typed_confirm: Callable[..., Awaitable[PermissionResponse]],
        request_secrets_input: Callable[..., Awaitable[PermissionResponse]],
        allow_set: set[str],
        logger: StructuredLogger | None,
    ) -> None:
        self.cwd = cwd
        self.abort_signal = abort_signal
        self.session_id = session_id
        self.provider_name = provider_name
        self.model = model
        self.request_permission = request_permission
        self.request_confirm = request_confirm
        self.request_typed_confirm = request_typed_confirm
        self.request_secrets_input = request_secrets_input
        self.allow_set = allow_set
        self.logger = logger
        self.resources: list[dict[str, Any]] = []


DeferredBase = dict[
    str, Any
]  # permission_request | action_review | typed_confirm_request | secrets_input_request


class QueryEngine:
    """Manages one conversation session and drives AgentBackend turns."""

    def __init__(
        self,
        *,
        cwd: str,
        provider: Provider,
        model: str | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._cwd = cwd
        self.provider = provider
        self.model = model
        self._session_store = session_store

        self._messages: list[Message] = []
        self._pending: dict[str, asyncio.Future[PermissionResponse]] = {}
        self._session_allow_set: set[str] = set()
        self._active_controller: asyncio.Event | None = None
        self._session_id = _nanoid()
        self._resumed_id: str | None = None
        self._session_created_at: str | None = None
        self._logger: StructuredLogger | None = None
        self._current_iteration = 0
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self._activity_snapshot: list[ActivityItem] | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def is_resumed(self) -> bool:
        return self._resumed_id is not None

    def load_session(self, record: SessionRecord) -> str | None:
        if record.get("schema_version") != 1:
            return None
        self._messages = _MessageListAdapter.validate_python(record.get("messages", []))
        self._resumed_id = record["id"]
        self._session_id = record["id"]
        self._session_created_at = record.get("created_at")
        if record.get("model") is not None:
            self.model = record["model"]
        raw_activities = record.get("activities")
        if isinstance(raw_activities, list):
            self._activity_snapshot = deserialize_activity_items(raw_activities)
        self._pending.clear()
        self._session_allow_set.clear()
        warning = session_cwd_mismatch_warning(record, self._cwd)
        if warning:
            sys.stderr.write(f"[docker-agent] {warning}\n")
        return warning

    def get_messages(self) -> list[Message]:
        return list(self._messages)

    def get_activity_snapshot(self) -> list[ActivityItem] | None:
        return None if self._activity_snapshot is None else list(self._activity_snapshot)

    def set_activity_snapshot(self, items: list[ActivityItem]) -> None:
        self._activity_snapshot = list(items)

    def set_logger(self, logger: StructuredLogger) -> None:
        self._logger = logger

    def _persist_session(self, *, resources: list[dict[str, Any]] | None = None) -> None:
        if self._session_store is None or not self._messages:
            return
        now = datetime.now(UTC).isoformat()
        if self._session_created_at is None:
            self._session_created_at = now
        first_user = next((m for m in self._messages if isinstance(m, UserMessage)), None)
        first_prompt = first_user.content if first_user is not None else "(empty)"
        provider_name = getattr(self.provider, "name", "unknown")
        effective_resources = list(resources or [])
        record: SessionRecord = {
            "schema_version": 1,
            "id": self._session_id,
            "created_at": self._session_created_at,
            "updated_at": now,
            "cwd": self._cwd,
            "provider": provider_name,
            "model": self.model,
            "first_prompt": first_prompt,
            "stack_names": [str(resource.get("name", "")) for resource in effective_resources],
            "resources": effective_resources,
            "messages": [m.model_dump(by_alias=True) for m in self._messages],
        }
        if self._activity_snapshot is not None:
            record["activities"] = serialize_activity_items(self._activity_snapshot)
        self._session_store.save(record)

    def persist_session(self) -> None:
        """Persist current session snapshot immediately."""
        self._persist_session()

    async def query(self, user_input: str) -> AsyncIterator[LoopEvent]:
        controller = asyncio.Event()
        self._active_controller = controller
        self._messages.append(UserMessage(content=user_input))
        if self._logger is not None:
            self._logger.log(
                LogEntry(
                    ts=datetime.now(UTC).isoformat(),
                    level="info",
                    session_id=self._session_id,
                    category="turn_start",
                    message=user_input,
                )
            )
        event_queue: AsyncQueue[LoopEvent] = AsyncQueue()

        def defer(deferred: DeferredBase) -> asyncio.Future[PermissionResponse]:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[PermissionResponse] = loop.create_future()
            request_id = _nanoid()
            event = _LoopEventAdapter.validate_python({**deferred, "id": request_id})
            asyncio.create_task(event_queue.push(event))
            self._pending[request_id] = future
            return future

        async def request_permission(tool: str, input_data: Any) -> PermissionResponse:
            return await defer({"type": "permission_request", "tool": tool, "input": input_data})

        async def request_confirm(
            review: ActionReviewPayload | dict[str, Any],
        ) -> PermissionResponse:
            if not isinstance(review, ActionReviewPayload):
                review = ActionReviewPayload.model_validate(review)
            return await defer(
                {
                    "type": "action_review",
                    **review.model_dump(by_alias=True),
                }
            )

        async def request_typed_confirm(phrase: str, reason: str) -> PermissionResponse:
            return await defer(
                {"type": "typed_confirm_request", "phrase": phrase, "reason": reason}
            )

        async def request_secrets_input(
            service: str, keys: list[str], reason: str
        ) -> PermissionResponse:
            return await defer(
                {
                    "type": "secrets_input_request",
                    "service": service,
                    "keys": keys,
                    "reason": reason,
                }
            )

        ctx = _QueryLoopContext(
            cwd=self._cwd,
            abort_signal=controller,
            session_id=self._session_id,
            provider_name=self.provider.name,
            model=self.model,
            request_permission=request_permission,
            request_confirm=request_confirm,
            request_typed_confirm=request_typed_confirm,
            request_secrets_input=request_secrets_input,
            allow_set=self._session_allow_set,
            logger=self._logger,
        )

        backend = create_backend()
        backend_params = BackendQueryParams(
            messages=self._messages,
            ctx=ctx,
            provider=self.provider,
            model=self.model,
        )

        async def runner() -> None:
            try:
                async for ev in backend.query(backend_params):
                    await event_queue.push(ev)
            except Exception as err:
                if not controller.is_set():
                    await event_queue.push(Error(error=err))
            finally:
                event_queue.close()
                deny = PermissionResponseAdapter.validate_python({"kind": "deny"})
                for future in self._pending.values():
                    if not future.done():
                        future.set_result(deny)
                self._pending.clear()

        task = asyncio.create_task(runner())
        try:
            async for ev in event_queue:
                if ev.type == "usage":
                    self.total_usage["input_tokens"] += ev.input_tokens
                    self.total_usage["output_tokens"] += ev.output_tokens
                if self._logger is not None:
                    self._logger.log(self._to_log_entry(ev))
                yield ev
        finally:
            self._active_controller = None
            with contextlib.suppress(Exception):
                await task
            self._messages = list(backend_params.messages)
            if self._logger is not None:
                self._logger.log(
                    LogEntry(
                        ts=datetime.now(UTC).isoformat(),
                        level="info",
                        session_id=self._session_id,
                        category="turn_end",
                        message="turn complete",
                    )
                )
                self._logger.close()
            resources = list(getattr(ctx, "resources", []))
            self._persist_session(resources=resources)

    def respond_to(self, request_id: str, answer: PermissionResponse) -> bool:
        future = self._pending.get(request_id)
        if future is None:
            return False
        self._pending.pop(request_id, None)
        if not future.done():
            future.set_result(answer)
        return True

    def abort(self) -> None:
        if self._active_controller is not None:
            self._active_controller.set()
        deny = PermissionResponseAdapter.validate_python({"kind": "deny"})
        for future in self._pending.values():
            if not future.done():
                future.set_result(deny)
        self._pending.clear()

    def reset(self) -> None:
        self.abort()
        self._messages = []
        self._pending.clear()
        self._session_allow_set.clear()
        self._active_controller = None
        self._resumed_id = None
        self._session_created_at = None
        self._session_id = _nanoid()
        self._activity_snapshot = None

    def _to_log_entry(self, ev: LoopEvent) -> LogEntry:
        ts = datetime.now(UTC).isoformat()
        session_id = self._session_id
        iteration = self._current_iteration

        if isinstance(ev, IterationStart):
            self._current_iteration = ev.n
            near_limit = ev.n >= math.ceil(MAX_ITERATIONS * 0.8)
            return LogEntry(
                ts=ts,
                level="warn" if near_limit else "info",
                session_id=session_id,
                iteration=ev.n,
                category="iteration_start",
                message=(
                    f"iteration {ev.n} (approaching limit: {ev.n}/{MAX_ITERATIONS})"
                    if near_limit
                    else f"iteration {ev.n}"
                ),
            )
        if isinstance(ev, AssistantText):
            return LogEntry(
                ts=ts,
                level="debug",
                session_id=session_id,
                iteration=iteration,
                category="thought_delta",
                message="assistant text delta",
                data={"text": ev.delta},
            )
        if isinstance(ev, ToolCall):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="action",
                message=f"tool_call: {ev.name}",
                data={"name": ev.name, "input": ev.input},
            )
        if isinstance(ev, ToolProgress):
            return LogEntry(
                ts=ts,
                level="debug",
                session_id=session_id,
                iteration=iteration,
                category="progress",
                message=ev.msg,
            )
        if isinstance(ev, ToolResult):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="observation",
                message=f"tool_result: {ev.name}",
                data={"name": ev.name, "output": ev.output},
            )
        if isinstance(ev, ActionReview):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="action_review",
                message=f"action review: {ev.tool}",
            )
        if isinstance(ev, PermissionRequest):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="permission_request",
                message=f"permission: {ev.tool}",
            )
        if isinstance(ev, Error):
            stack = ""
            if isinstance(ev.error, BaseException):
                import traceback

                stack = "".join(
                    traceback.format_exception(type(ev.error), ev.error, ev.error.__traceback__)
                )
            return LogEntry(
                ts=ts,
                level="error",
                session_id=session_id,
                iteration=iteration,
                category="error",
                message=str(ev.error),
                data={"stack": stack},
            )
        if isinstance(ev, Usage):
            return LogEntry(
                ts=ts,
                level="debug",
                session_id=session_id,
                iteration=iteration,
                category="usage",
                message=f"tokens: {ev.input_tokens} in / {ev.output_tokens} out",
                data={"input_tokens": ev.input_tokens, "output_tokens": ev.output_tokens},
            )
        if isinstance(ev, RollbackStarted):
            return LogEntry(
                ts=ts,
                level="warn",
                session_id=session_id,
                iteration=iteration,
                category="rollback_started",
                message=f"rollback: {ev.stack_name} ({ev.reason})",
            )
        if isinstance(ev, RollbackResult):
            return LogEntry(
                ts=ts,
                level="info" if ev.ok else "error",
                session_id=session_id,
                iteration=iteration,
                category="rollback_result",
                message=f"rollback {'ok' if ev.ok else 'failed'}: {ev.stack_name}",
            )
        return LogEntry(
            ts=ts,
            level="debug",
            session_id=session_id,
            iteration=iteration,
            category="event",
            message=f"event: {ev.type}",
        )


def restore_session_from_record(
    *,
    engine: QueryEngine,
    record: SessionRecord,
    api_key_store: Any,
) -> str | None:
    """Load a saved session and re-bind the LLM provider from the record."""
    from infra_agent.services.api import resolve_provider_for_request

    warning = engine.load_session(record)
    provider_name = record.get("provider")
    if isinstance(provider_name, str) and is_valid_provider(provider_name):
        engine.provider = resolve_provider_for_request(
            provider_name,  # type: ignore[arg-type]
            os.environ,
            api_key_store=api_key_store,
        )
    return warning


__all__ = ["QueryEngine", "restore_session_from_record"]

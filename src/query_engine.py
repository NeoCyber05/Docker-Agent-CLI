"""Reusable query engine orchestrating a backend turn.

Parity: ``src/QueryEngine.ts``.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter

from src.agent import BackendQueryParams, create_backend
from src.loop_context import PlanReadyPayload
from src.services.api.types import Provider
from src.services.docker.compose_runner import ComposeRunner
from src.state.logger import LogEntry, StructuredLogger
from src.state.session_store import (
    SessionRecord,
    SessionStore,
    session_cwd_mismatch_warning,
)
from src.state.state_store import StateStore
from src.types.events import (
    AssistantText,
    Error,
    IterationStart,
    LoopEvent,
    PermissionRequest,
    PlanReady,
    RollbackResult,
    RollbackStarted,
    ToolCall,
    ToolProgress,
    ToolResult,
    Usage,
)
from src.types.message import Message, UserMessage
from src.types.permissions import PermissionResponse, PermissionResponseAdapter
from src.utils.async_queue import AsyncQueue

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
        state_store: StateStore,
        docker_engine: Any,
        compose_runner: ComposeRunner,
        abort_signal: asyncio.Event,
        session_id: str,
        health_check_deadline_ms: int | None,
        request_permission: Callable[..., Awaitable[PermissionResponse]],
        request_confirm: Callable[..., Awaitable[PermissionResponse]],
        request_typed_confirm: Callable[..., Awaitable[PermissionResponse]],
        request_secrets_input: Callable[..., Awaitable[PermissionResponse]],
        allow_set: set[str],
        logger: StructuredLogger | None,
    ) -> None:
        self.cwd = cwd
        self.state_store = state_store
        self.docker_engine = docker_engine
        self.compose_runner = compose_runner
        self.abort_signal = abort_signal
        self.image_validator = None
        self.session_id = session_id
        self.health_check_deadline_ms = health_check_deadline_ms
        self.request_permission = request_permission
        self.request_confirm = request_confirm
        self.request_typed_confirm = request_typed_confirm
        self.request_secrets_input = request_secrets_input
        self.allow_set = allow_set
        self.logger = logger


DeferredBase = (
    dict[str, Any]
)  # permission_request | plan_ready | typed_confirm_request | secrets_input_request


class QueryEngine:
    """Manages one conversation session and drives AgentBackend turns."""

    def __init__(
        self,
        *,
        cwd: str,
        state_store: StateStore,
        docker_engine: Any,
        compose_runner: ComposeRunner,
        provider: Provider,
        model: str | None = None,
        session_store: SessionStore | None = None,
        health_check_deadline_ms: int | None = None,
    ) -> None:
        self._cwd = cwd
        self._state_store = state_store
        self._docker_engine = docker_engine
        self._compose_runner = compose_runner
        self.provider = provider
        self.model = model
        self._session_store = session_store
        self._health_check_deadline_ms = health_check_deadline_ms

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
        self._pending.clear()
        self._session_allow_set.clear()
        warning = session_cwd_mismatch_warning(record, self._cwd)
        if warning:
            sys.stderr.write(f"[docker-agent] {warning}\n")
        return warning

    def get_messages(self) -> list[Message]:
        return list(self._messages)

    def set_logger(self, logger: StructuredLogger) -> None:
        self._logger = logger

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

        async def request_permission(
            tool: str, input_data: Any
        ) -> PermissionResponse:
            return await defer(
                {"type": "permission_request", "tool": tool, "input": input_data}
            )

        async def request_confirm(plan: PlanReadyPayload | dict[str, Any]) -> PermissionResponse:
            if not isinstance(plan, PlanReadyPayload):
                plan = PlanReadyPayload.model_validate(plan)
            payload: dict[str, Any] = {
                "type": "plan_ready",
                "compose_yaml": plan.compose_yaml,
                "diff": plan.diff,
            }
            if plan.auto_generated_secrets:
                payload["auto_generated_secrets"] = plan.auto_generated_secrets
            if plan.config_files:
                payload["config_files"] = plan.config_files
            return await defer(payload)

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
            state_store=self._state_store,
            docker_engine=self._docker_engine,
            compose_runner=self._compose_runner,
            abort_signal=controller,
            session_id=self._session_id,
            health_check_deadline_ms=self._health_check_deadline_ms,
            request_permission=request_permission,
            request_confirm=request_confirm,
            request_typed_confirm=request_typed_confirm,
            request_secrets_input=request_secrets_input,
            allow_set=self._session_allow_set,
            logger=self._logger,
        )

        backend = create_backend()

        async def runner() -> None:
            try:
                async for ev in backend.query(
                    BackendQueryParams(
                        messages=self._messages,
                        ctx=ctx,
                        provider=self.provider,
                        model=self.model,
                    )
                ):
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
            if self._session_store is not None:
                now = datetime.now(UTC).isoformat()
                if self._session_created_at is None:
                    self._session_created_at = now
                first_user = next(
                    (m for m in self._messages if isinstance(m, UserMessage)),
                    None,
                )
                first_prompt = first_user.content if first_user is not None else "(empty)"
                provider_name = getattr(self.provider, "name", "unknown")
                self._session_store.save(
                    {
                        "schema_version": 1,
                        "id": self._session_id,
                        "created_at": self._session_created_at,
                        "updated_at": now,
                        "cwd": self._cwd,
                        "provider": provider_name,
                        "model": self.model,
                        "first_prompt": first_prompt,
                        "stack_names": [s.name for s in self._state_store.list()],
                        "messages": [m.model_dump(by_alias=True) for m in self._messages],
                    }
                )

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

    def _to_log_entry(self, ev: LoopEvent) -> LogEntry:
        ts = datetime.now(UTC).isoformat()
        session_id = self._session_id
        iteration = self._current_iteration

        if isinstance(ev, IterationStart):
            self._current_iteration = ev.n
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=ev.n,
                category="iteration_start",
                message=f"iteration {ev.n}",
            )
        if isinstance(ev, AssistantText):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="thought",
                message="assistant text",
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
        if isinstance(ev, PlanReady):
            return LogEntry(
                ts=ts,
                level="info",
                session_id=session_id,
                iteration=iteration,
                category="plan_ready",
                message="plan ready for confirmation",
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
                data={
                    "input_tokens": ev.input_tokens,
                    "output_tokens": ev.output_tokens,
                },
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


__all__ = ["QueryEngine"]
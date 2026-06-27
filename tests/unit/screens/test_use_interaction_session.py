"""Tests for InteractionSession."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.screens.use_interaction_session import InteractionSession
from src.types.events import (
    AssistantText,
    PermissionRequest,
    ToolCall,
    ToolResult,
)
from src.types.permissions import Approve


class MockQueryEngine:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []
        self._messages: list[Any] = []
        self._pending: dict[str, asyncio.Future[None]] = {}
        self.aborted = False
        self.reset_called = False
        self.responded: list[tuple[str, Any]] = []

    def get_messages(self) -> list[Any]:
        return list(self._messages)

    def abort(self) -> None:
        self.aborted = True
        for future in self._pending.values():
            if not future.done():
                future.set_result(None)
        self._pending.clear()

    def reset(self) -> None:
        self.reset_called = True
        self._messages = []

    def respond_to(self, request_id: str, answer: Any) -> bool:
        self.responded.append((request_id, answer))
        future = self._pending.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(None)
        return future is not None

    async def query(self, user_input: str) -> AsyncIterator[Any]:
        self._messages.append({"role": "user", "content": user_input})
        for event in self._events:
            if isinstance(event, PermissionRequest):
                loop = asyncio.get_running_loop()
                future: asyncio.Future[None] = loop.create_future()
                self._pending[event.id] = future
                yield event
                await future
            else:
                yield event


@pytest.mark.asyncio
async def test_text_turn_produces_assistant_text_activity() -> None:
    engine = MockQueryEngine([AssistantText(delta="hello world")])
    session = InteractionSession(engine)

    session.submit("hi")
    await session.run_turn("hi")

    assert any(
        item.type == "text" and item.role == "assistant" and item.text == "hello world"
        for item in session.activities
    )
    assert session.phase == "idle"


@pytest.mark.asyncio
async def test_permission_request_pauses_interaction() -> None:
    engine = MockQueryEngine(
        [PermissionRequest(id="req-1", tool="pull_image", input={"image": "nginx"})]
    )
    session = InteractionSession(engine)

    task = asyncio.create_task(session.run_turn("pull nginx"))
    for _ in range(50):
        if session.pending_event is not None:
            break
        await asyncio.sleep(0.01)

    assert session.phase == "awaiting_input"
    assert session.pending_event is not None
    assert session.pending_event.type == "permission_request"
    session.respond("req-1", Approve())
    await task
    assert session.phase == "idle"


@pytest.mark.asyncio
async def test_respond_resumes_and_produces_tool_result() -> None:
    engine = MockQueryEngine(
        [
            PermissionRequest(id="req-1", tool="pull_image", input={"image": "nginx"}),
            ToolCall(name="pull_image", input={"image": "nginx"}),
            ToolResult(name="pull_image", output={"ok": True}),
        ]
    )
    session = InteractionSession(engine)

    async def run_with_response() -> None:
        task = asyncio.create_task(session.run_turn("pull nginx"))
        for _ in range(50):
            if session.pending_event is not None:
                session.respond("req-1", Approve())
                break
            await asyncio.sleep(0.01)
        await task

    await run_with_response()

    assert session.pending_event is None
    assert session.phase == "idle"
    assert any(item.type == "tool" and item.status == "completed" for item in session.activities)


@pytest.mark.asyncio
async def test_cancel_marks_active_tool_cancelled() -> None:
    engine = MockQueryEngine([ToolCall(name="list_stacks", input={})])
    session = InteractionSession(engine)

    async def run_and_cancel() -> None:
        task = asyncio.create_task(session.run_turn("list"))
        await asyncio.sleep(0.01)
        session.cancel_current()
        await task

    await run_and_cancel()

    assert engine.aborted is True
    assert any(
        item.type == "tool" and item.status == "cancelled" for item in session.activities
    )


@pytest.mark.asyncio
async def test_queue_processes_multiple_prompts() -> None:
    calls: list[str] = []

    class TrackingEngine(MockQueryEngine):
        async def query(self, user_input: str) -> AsyncIterator[Any]:
            calls.append(user_input)
            async for event in super().query(user_input):
                yield event

    engine = TrackingEngine([AssistantText(delta="ok")])
    session = InteractionSession(engine)

    session.submit("first")
    await session.run_turn("first")
    session.submit("second")
    session.submit("third")
    await session.run_turn("second")
    await session.run_turn("third")

    assert calls == ["first", "second", "third"]
    assert session.queue == []


@pytest.mark.asyncio
async def test_run_loop_starts_submitted_turn() -> None:
    calls: list[str] = []

    class TrackingEngine(MockQueryEngine):
        async def query(self, user_input: str) -> AsyncIterator[Any]:
            calls.append(user_input)
            yield AssistantText(delta="done")

    engine = TrackingEngine()
    session = InteractionSession(engine)
    session.submit("hello")

    loop_task = asyncio.create_task(session.run_loop())
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.05)
    loop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop_task

    assert calls == ["hello"]


def test_reset_clears_state() -> None:
    engine = MockQueryEngine()
    session = InteractionSession(engine)
    session.submit("queued while idle")
    session.dispatch_activity({"type": "user_text", "text": "visible"})
    session.reset()

    assert engine.reset_called is True
    assert session.activities == []
    assert session.pending_event is None
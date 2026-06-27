"""Async queue with close/abort semantics.

Parity: ``src/utils/AsyncQueue.ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Generic, TypeVar

T = TypeVar("T")


class AsyncQueue(Generic[T]):
    """Wraps asyncio.Queue with a sentinel for graceful shutdown."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[T | None] = asyncio.Queue()
        self._closed = False

    async def push(self, item: T) -> None:
        if self._closed:
            return
        await self._queue.put(item)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)

    def abort(self) -> None:
        self.close()

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
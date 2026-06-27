"""Bridge blocking (synchronous) iterators into async iterators.

Provider SDKs (OpenAI, Ollama, Gemini) expose *synchronous* streaming
generators. Iterating them directly inside an ``async def`` generator blocks
the single asyncio event loop that drives the Textual UI, freezing the spinner,
the elapsed-time counter, and delaying when freshly submitted prompts are drawn.

``aiter_in_thread`` runs the blocking iteration on a worker thread and hands
each produced item back to the event loop via a thread-safe queue, so the UI
stays responsive while tokens stream in.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Iterator
from typing import TypeVar

T = TypeVar("T")

_DONE = object()


async def aiter_in_thread(make_iter: Callable[[], Iterator[T]]) -> AsyncIterator[T]:
    """Yield items from a blocking iterator without blocking the event loop.

    ``make_iter`` is called on a worker thread and must return a synchronous
    iterator. Each yielded item is forwarded to the caller on the event loop.
    Exceptions raised while building or iterating are re-raised on the
    consuming side, preserving normal ``async for`` error semantics.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[bool, object]] = asyncio.Queue()

    def producer() -> None:
        try:
            for item in make_iter():
                loop.call_soon_threadsafe(queue.put_nowait, (True, item))
        except Exception as err:  # noqa: BLE001 - surfaced to the consumer
            loop.call_soon_threadsafe(queue.put_nowait, (False, err))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, (False, _DONE))

    task = loop.run_in_executor(None, producer)
    try:
        while True:
            ok, payload = await queue.get()
            if ok:
                yield payload  # type: ignore[misc]
            elif payload is _DONE:
                break
            else:
                raise payload  # type: ignore[misc]
    finally:
        with contextlib.suppress(Exception):
            await task


__all__ = ["aiter_in_thread"]

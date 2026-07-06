import pytest

from docker_agent.utils.async_queue import AsyncQueue


@pytest.mark.asyncio
async def test_async_queue_push_and_close() -> None:
    q = AsyncQueue[str]()
    await q.push("a")
    await q.push("b")
    q.close()
    items = [item async for item in q]
    assert items == ["a", "b"]

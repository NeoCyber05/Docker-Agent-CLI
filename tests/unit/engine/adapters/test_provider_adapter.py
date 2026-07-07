import pytest

from infra_agent.engine.adapters.provider_adapter import drive_provider
from infra_agent.services.api.types import TextDeltaEvent, ToolUseStartEvent, UsageEvent
from infra_agent.types.message import UserMessage


@pytest.mark.asyncio
async def test_drive_provider_collects_turn(make_loop_ctx) -> None:
    ctx = make_loop_ctx()

    class FakeProvider:
        name = "fake"

        async def stream(self, _params):
            yield TextDeltaEvent(text="hello")
            yield ToolUseStartEvent(id="t1", name="list_stacks")
            yield UsageEvent(input_tokens=3, output_tokens=2)

    events = []
    turn = await drive_provider(
        provider=FakeProvider(),
        messages=[UserMessage(content="hi")],
        ctx=ctx,
        on_event=events.append,
    )
    assert turn.text == "hello"
    assert len(turn.tool_uses) == 1
    assert any(e.type == "assistant_text" for e in events)

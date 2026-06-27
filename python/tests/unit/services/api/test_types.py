"""Parity tests for provider API types."""

from docker_agent.services.api.types import (
    ErrorEvent,
    MessageStopEvent,
    ProviderEvent,
    TextDeltaEvent,
    ToolUseStartEvent,
    UsageEvent,
)


def test_provider_event_union_discriminates() -> None:
    events: list[ProviderEvent] = [
        TextDeltaEvent(text="hello"),
        ToolUseStartEvent(id="1", name="plan_stack"),
        UsageEvent(input_tokens=1, output_tokens=2),
        ErrorEvent(error=ValueError("boom")),
        MessageStopEvent(stop_reason="tool_use"),
    ]
    assert events[0].type == "text_delta"
    assert events[1].type == "tool_use_start"
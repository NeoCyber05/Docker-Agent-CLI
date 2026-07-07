"""Parity tests for Ollama provider."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from infra_agent.services.api.providers.ollama import OllamaProvider
from infra_agent.services.api.types import CallModelParams, ToolSchema
from infra_agent.types.message import UserMessage
from tests.unit.services.api.conftest import drain_events


class DummyInput(BaseModel):
    stack_name: str


@pytest.mark.asyncio
async def test_ollama_yields_text_delta_and_usage() -> None:
    provider = OllamaProvider()
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[ToolSchema(name="plan_stack", description="plan", input_schema=DummyInput)],
        system="sys",
    )

    fake_part = MagicMock()
    fake_part.message.content = "hi"
    fake_part.message.tool_calls = None
    fake_part.eval_count = 7

    with patch("ollama.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = [fake_part]
        mock_cls.return_value = mock_client

        events = await drain_events(provider.stream(params))

    types = [e.type for e in events]
    assert "text_delta" in types
    assert "usage" in types
    assert "message_stop" in types

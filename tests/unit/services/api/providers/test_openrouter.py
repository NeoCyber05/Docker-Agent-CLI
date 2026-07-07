"""Parity tests for OpenRouter provider."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from infra_agent.services.api.providers.openrouter import OpenRouterProvider
from infra_agent.services.api.types import CallModelParams, ToolSchema
from infra_agent.types.message import UserMessage
from tests.unit.services.api.conftest import drain_events


class DummyInput(BaseModel):
    stack_name: str


@pytest.mark.asyncio
async def test_openrouter_uses_openrouter_base_url() -> None:
    provider = OpenRouterProvider(env={"OPENROUTER_API_KEY": "test"})
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[ToolSchema(name="plan_stack", description="plan", input_schema=DummyInput)],
        system="sys",
    )

    fake_chunk = MagicMock()
    fake_chunk.choices = [MagicMock(delta=MagicMock(content="ok"), finish_reason="stop")]
    fake_chunk.usage = MagicMock(prompt_tokens=2, completion_tokens=1)

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter([fake_chunk])
        mock_client_cls.return_value = mock_client

        events = await drain_events(provider.stream(params))

    assert mock_client_cls.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert any(e.type == "text_delta" for e in events)

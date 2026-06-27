"""Parity tests for Gemini provider."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.services.api.providers.gemini import GeminiProvider
from src.services.api.types import CallModelParams, ToolSchema
from src.types.message import UserMessage
from tests.unit.services.api.conftest import drain_events


class DummyInput(BaseModel):
    stack_name: str


@pytest.mark.asyncio
async def test_gemini_yields_text_delta_and_usage() -> None:
    provider = GeminiProvider(env={"GEMINI_API_KEY": "test"})
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[ToolSchema(name="plan_stack", description="plan", input_schema=DummyInput)],
        system="sys",
    )

    fake_part = MagicMock()
    fake_part.text = "hi"
    fake_part.thought = False
    fake_part.function_call = None
    fake_cand = MagicMock()
    fake_cand.finish_reason = "STOP"
    fake_cand.content.parts = [fake_part]
    fake_chunk = MagicMock()
    fake_chunk.candidates = [fake_cand]
    fake_chunk.prompt_feedback = None
    fake_chunk.usage_metadata = MagicMock(prompt_token_count=4, candidates_token_count=2)

    with patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = [fake_chunk]
        mock_model_cls.return_value = mock_model

        events = await drain_events(provider.stream(params))

    types = [e.type for e in events]
    assert "text_delta" in types
    assert "usage" in types
    assert "message_stop" in types
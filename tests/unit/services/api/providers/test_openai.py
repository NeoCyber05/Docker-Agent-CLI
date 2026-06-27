"""Parity tests for OpenAI provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.services.api.providers.openai import OpenAIProvider
from src.services.api.types import CallModelParams, ToolSchema
from src.types.message import UserMessage
from src.vault.api_key_store import MemoryApiKeyStore
from tests.unit.services.api.conftest import drain_events


class DummyInput(BaseModel):
    stack_name: str


def _make_provider() -> OpenAIProvider:
    return OpenAIProvider(
        env={"OPENAI_API_KEY": "test"},
        api_key_store=MemoryApiKeyStore(),
    )


@pytest.mark.asyncio
async def test_stream_yields_text_delta_and_usage() -> None:
    provider = _make_provider()
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[ToolSchema(name="plan_stack", description="plan", input_schema=DummyInput)],
        system="sys",
    )

    fake_chunk_text = MagicMock()
    fake_chunk_text.choices = [
        MagicMock(
            delta=MagicMock(content="hi", tool_calls=None),
            finish_reason=None,
        )
    ]
    fake_chunk_text.usage = None
    fake_chunk_stop = MagicMock()
    fake_chunk_stop.choices = [MagicMock(delta=MagicMock(content=None), finish_reason="stop")]
    fake_chunk_stop.usage = MagicMock(prompt_tokens=5, completion_tokens=3)

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(
            [fake_chunk_text, fake_chunk_stop]
        )
        mock_client_cls.return_value = mock_client

        events = await drain_events(provider.stream(params))

    types = [e.type for e in events]
    assert "text_delta" in types
    assert "usage" in types
    assert "message_stop" in types


@pytest.mark.asyncio
async def test_stream_missing_api_key_yields_error() -> None:
    provider = OpenAIProvider(env={}, api_key_store=MemoryApiKeyStore())
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[],
        system="sys",
    )
    events = await drain_events(provider.stream(params))
    assert len(events) == 1
    assert events[0].type == "error"


@pytest.mark.asyncio
async def test_stream_tool_calls() -> None:
    provider = _make_provider()
    params = CallModelParams(
        messages=[UserMessage(role="user", content="hello")],
        tools=[ToolSchema(name="plan_stack", description="plan", input_schema=DummyInput)],
        system="sys",
    )

    start_fn = MagicMock()
    start_fn.name = "plan_stack"
    start_fn.arguments = '{"stack'
    delta_fn = MagicMock()
    delta_fn.name = None
    delta_fn.arguments = '_name":"x"}'

    fake_tool_start = MagicMock()
    fake_tool_start.choices = [
        MagicMock(
            delta=MagicMock(
                content=None,
                tool_calls=[MagicMock(index=0, id="call-1", function=start_fn)],
            ),
            finish_reason=None,
        )
    ]
    fake_tool_start.usage = None

    fake_tool_delta = MagicMock()
    fake_tool_delta.choices = [
        MagicMock(
            delta=MagicMock(
                content=None,
                tool_calls=[MagicMock(index=0, id=None, function=delta_fn)],
            ),
            finish_reason=None,
        )
    ]
    fake_tool_delta.usage = None

    fake_tool_stop = MagicMock()
    fake_tool_stop.choices = [
        MagicMock(delta=MagicMock(content=None, tool_calls=None), finish_reason="tool_calls")
    ]
    fake_tool_stop.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(
            [fake_tool_start, fake_tool_delta, fake_tool_stop]
        )
        mock_client_cls.return_value = mock_client

        events = await drain_events(provider.stream(params))

    types = [e.type for e in events]
    assert "tool_use_start" in types
    assert "tool_use_delta" in types
    assert "tool_use_stop" in types
    stop_events = [e for e in events if e.type == "message_stop"]
    assert stop_events[0].stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_list_models() -> None:
    provider = _make_provider()
    mock_model = MagicMock()
    mock_model.id = "gpt-4o"
    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.list.return_value = MagicMock(data=[mock_model])
        mock_client_cls.return_value = mock_client
        models = await provider.list_models()
    assert models == ["gpt-4o"]
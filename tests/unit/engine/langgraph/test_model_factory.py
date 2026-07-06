"""Tests for native LangChain chat model construction."""

from __future__ import annotations

import pytest

from docker_agent.engine.langgraph.model_factory import create_chat_model


def test_create_chat_model_maps_openrouter_to_openai_compatible_endpoint() -> None:
    model = create_chat_model(
        provider_name="openrouter",
        model="openai/gpt-4o-mini",
        env={"OPENROUTER_API_KEY": "sk-test"},
    )

    assert model.__class__.__name__ == "ChatOpenAI"
    assert str(model.openai_api_base).rstrip("/") == "https://openrouter.ai/api/v1"
    assert model.model_name == "openai/gpt-4o-mini"


@pytest.mark.parametrize(
    ("provider_name", "expected_class"),
    [
        ("openai", "ChatOpenAI"),
        ("gemini", "ChatGoogleGenerativeAI"),
        ("ollama", "ChatOllama"),
    ],
)
def test_create_chat_model_maps_supported_providers(
    provider_name: str,
    expected_class: str,
) -> None:
    model = create_chat_model(
        provider_name=provider_name,
        model="test-model",
        env={
            "OPENAI_API_KEY": "sk-test",
            "GEMINI_API_KEY": "gemini-test",
            "OLLAMA_HOST": "http://localhost:11434",
        },
    )

    assert model.__class__.__name__ == expected_class


def test_create_chat_model_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported LangChain provider"):
        create_chat_model(provider_name="unknown", model=None, env={})


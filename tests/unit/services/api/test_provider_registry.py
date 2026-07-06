"""Provider registry smoke tests."""

from docker_agent.services.api import (
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
)


def test_all_providers_expose_name() -> None:
    assert OpenAIProvider(env={"OPENAI_API_KEY": "x"}).name == "openai"
    assert OpenRouterProvider(env={"OPENROUTER_API_KEY": "x"}).name == "openrouter"
    assert GeminiProvider(env={"GEMINI_API_KEY": "x"}).name == "gemini"
    assert OllamaProvider().name == "ollama"

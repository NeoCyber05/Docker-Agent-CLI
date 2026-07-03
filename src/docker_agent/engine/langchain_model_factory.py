"""Native LangChain chat model factory."""

from __future__ import annotations

from collections.abc import Mapping

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "qwen2.5:14b",
    "openrouter": "openai/gpt-4o-mini",
}


def create_chat_model(
    *,
    provider_name: str,
    model: str | None,
    env: Mapping[str, str],
) -> BaseChatModel:
    """Create a native LangChain chat model for a docker-agent provider."""
    selected = model or _DEFAULT_MODELS.get(provider_name)
    if provider_name == "openai":
        return ChatOpenAI(
            model=selected or _DEFAULT_MODELS["openai"],
            api_key=env.get("OPENAI_API_KEY"),
        )
    if provider_name == "gemini":
        return ChatGoogleGenerativeAI(
            model=selected or _DEFAULT_MODELS["gemini"],
            google_api_key=env.get("GEMINI_API_KEY"),
        )
    if provider_name == "ollama":
        return ChatOllama(
            model=selected or _DEFAULT_MODELS["ollama"],
            base_url=env.get("OLLAMA_HOST") or "http://localhost:11434",
        )
    if provider_name == "openrouter":
        return ChatOpenAI(
            model=selected or _DEFAULT_MODELS["openrouter"],
            api_key=env.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )
    raise ValueError(f"Unsupported LangChain provider: {provider_name}")


__all__ = ["create_chat_model"]

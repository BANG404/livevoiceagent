"""Chat model construction for the visitor-registration agent."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.config import Settings


def _split_model_provider(model_name: str) -> tuple[str | None, str]:
    if ":" not in model_name:
        return None, model_name
    provider, resolved_model_name = model_name.split(":", 1)
    return provider.strip().lower(), resolved_model_name.strip()


def build_agent_model(settings: Settings) -> BaseChatModel:
    """Build the configured LangChain chat model from a provider-prefixed model id."""
    provider, model_name = _split_model_provider(settings.agent_model)

    if provider in (None, "google", "google_genai", "gemini"):
        kwargs: dict[str, Any] = {"model": model_name}
        if settings.google_api_key:
            kwargs["google_api_key"] = settings.google_api_key
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "openai":
        kwargs = {"model": model_name}
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        return ChatOpenAI(**kwargs)

    raise ValueError(
        f"Unsupported AGENT_MODEL provider prefix: {provider!r}. "
        "Use prefixes like 'google_genai:' or 'openai:'."
    )

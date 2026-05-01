"""Chat model construction for the visitor-registration agent."""

from __future__ import annotations

from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from agent.config import Settings


def build_agent_model(settings: Settings) -> ChatGoogleGenerativeAI:
    """Build the configured LangChain chat model.

    Gemini models are constructed explicitly so the runtime only depends on
    the Google GenAI integration package and configured API key.
    """
    kwargs: dict[str, Any] = {"model": settings.agent_model}

    if settings.google_api_key:
        kwargs["google_api_key"] = settings.google_api_key

    return ChatGoogleGenerativeAI(**kwargs)

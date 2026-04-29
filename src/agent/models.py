"""Chat model construction for the visitor-registration agent."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from agent.config import Settings


def build_agent_model(settings: Settings) -> ChatOpenAI:
    """Build the configured LangChain chat model.

    OpenAI-compatible models are constructed explicitly so providers such as
    DashScope can set their own base URL.
    """
    kwargs: dict[str, Any] = {"model": settings.agent_model}

    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
        kwargs["api_key"] = settings.openai_api_key
        kwargs["stream_usage"] = False
    elif settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key

    return ChatOpenAI(**kwargs)

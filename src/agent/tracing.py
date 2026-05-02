"""Langfuse tracing integration for LangChain/LangGraph agents."""

from __future__ import annotations

from agent.config import settings


def build_langfuse_handler():
    """Return a Langfuse CallbackHandler if credentials are configured, else None."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None

    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_base_url or None,
    )
    return CallbackHandler()

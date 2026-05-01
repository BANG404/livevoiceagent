import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.config import Settings
from agent.models import build_agent_model


def test_build_agent_model_uses_chat_google_generative_ai_for_prefixed_google_model() -> (
    None
):
    model = build_agent_model(
        Settings(
            agent_model="google_genai:gemini-2.5-flash",
            google_api_key="test-key",
        )
    )

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"
    assert model.google_api_key.get_secret_value() == "test-key"


def test_build_agent_model_keeps_plain_gemini_name_backward_compatible() -> None:
    model = build_agent_model(
        Settings(
            agent_model="gemini-2.5-flash",
            google_api_key="test-key",
        )
    )

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"


def test_build_agent_model_uses_chat_openai_for_openai_prefix() -> None:
    model = build_agent_model(
        Settings(
            agent_model="openai:gpt-4o-mini",
            openai_api_key="test-openai-key",
            openai_base_url="https://openai.example.com/v1",
        )
    )

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-4o-mini"
    assert model.openai_api_key.get_secret_value() == "test-openai-key"
    assert str(model.openai_api_base) == "https://openai.example.com/v1"
    assert model.model_kwargs == {}


def test_build_agent_model_sets_text_modalities_for_openai_audio_models() -> None:
    model = build_agent_model(
        Settings(
            agent_model="openai:step-audio-2-mini",
            openai_api_key="test-openai-key",
        )
    )

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "step-audio-2-mini"
    assert model.model_kwargs == {"modalities": ["text"]}


def test_build_agent_model_rejects_unknown_provider_prefix() -> None:
    with pytest.raises(ValueError, match="Unsupported AGENT_MODEL provider prefix"):
        build_agent_model(Settings(agent_model="unknown:model"))

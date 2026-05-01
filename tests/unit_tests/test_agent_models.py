from langchain_google_genai import ChatGoogleGenerativeAI

from agent.config import Settings
from agent.models import build_agent_model


def test_build_agent_model_uses_chat_google_generative_ai() -> None:
    model = build_agent_model(
        Settings(
            agent_model="gemini-2.5-flash",
            google_api_key="test-key",
        )
    )

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"
    assert model.google_api_key.get_secret_value() == "test-key"

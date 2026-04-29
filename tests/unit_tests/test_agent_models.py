from langchain_openai import ChatOpenAI

from agent.config import Settings
from agent.models import build_agent_model


def test_build_agent_model_uses_chat_openai_for_dashscope() -> None:
    model = build_agent_model(
        Settings(
            agent_model="qwen3.5-omni-flash",
            openai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            openai_api_key="test-key",
        )
    )

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "qwen3.5-omni-flash"
    assert model.openai_api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert model.openai_api_key.get_secret_value() == "test-key"
    assert model.stream_usage is False

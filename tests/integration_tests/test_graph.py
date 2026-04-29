import pytest

from agent.config import settings
from agent.graph import graph

pytestmark = pytest.mark.anyio


def _skip_unavailable_model() -> None:
    if not settings.agent_model:
        pytest.skip(
            "Set AGENT_MODEL to run integration tests.",
            allow_module_level=True,
        )

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your-"):
        pytest.skip(
            "Set OPENAI_API_KEY to run OpenAI-compatible integration tests.",
            allow_module_level=True,
        )


_skip_unavailable_model()


async def test_agent_smoke() -> None:
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "What is 19*3? Use tools if needed and answer with just the number.",
                }
            ]
        }
    )
    output_text = str(result["messages"][-1].content)
    assert "57" in output_text

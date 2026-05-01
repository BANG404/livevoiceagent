import base64
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from agent.config import settings
from agent.models import build_agent_model

pytestmark = pytest.mark.anyio


def _skip_unavailable_model() -> None:
    if not settings.agent_model:
        pytest.skip(
            "Set AGENT_MODEL to run integration tests.",
            allow_module_level=True,
        )

    if not settings.google_api_key or settings.google_api_key == "your-google-api-key":
        pytest.skip(
            "Set GOOGLE_API_KEY to run Gemini integration tests.",
            allow_module_level=True,
        )


def _fixture_audio_base64() -> str:
    audio_path = Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "testvoice.m4a"
    return base64.b64encode(audio_path.read_bytes()).decode("ascii")


_skip_unavailable_model()


async def test_langchain_model_recognizes_testvoice_audio() -> None:
    model = build_agent_model(settings)

    result = await model.ainvoke(
        [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "识别这段音频里说的内容。"
                            "只返回识别出的中文文本，不要加解释，不要补标点。"
                        ),
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": _fixture_audio_base64(),
                            "format": "m4a",
                        },
                    },
                ]
            )
        ]
    )

    output_text = result.text().strip()
    assert "红色" in output_text, output_text

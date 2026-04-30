import base64
import wave
from io import BytesIO

from fastapi.testclient import TestClient
from langgraph_sdk.schema import StreamPart

from voice.agent_stream import build_audio_user_message, extract_assistant_text_delta
import voice.app as voice_app_module
from voice.app import TextDeltaSegmenter, app, _parse_custom_parameters


def test_parse_custom_parameters_from_twilio_dict() -> None:
    assert _parse_custom_parameters(
        {"call_sid": "CA123", "caller": "+8613800001234"}
    ) == {
        "call_sid": "CA123",
        "caller": "+8613800001234",
    }


def test_parse_custom_parameters_from_parameter_list() -> None:
    assert _parse_custom_parameters([{"name": "call_sid", "value": "CA123"}]) == {
        "call_sid": "CA123"
    }


def test_voice_webhook_returns_welcome_and_stream(monkeypatch) -> None:
    monkeypatch.setattr(
        voice_app_module,
        "settings",
        type(
            "SettingsStub",
            (),
            {
                "websocket_base_url": "wss://example.ngrok-free.app",
                "twilio_welcome_message": "欢迎致电园区，请准备车牌号。",
            },
        )(),
    )
    client = TestClient(app)

    response = client.post("/voice", data={"CallSid": "CA123", "From": "+8613800001234"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Say" in response.text
    assert "欢迎致电园区，请准备车牌号。" in response.text
    assert "<Connect><Stream url=\"wss://example.ngrok-free.app/twilio/media\">" in response.text
    assert "<Parameter name=\"call_sid\" value=\"CA123\" />" in response.text
    assert "<Parameter name=\"caller\" value=\"+8613800001234\" />" in response.text


def test_build_audio_user_message_uses_multimodal_audio_block() -> None:
    message = build_audio_user_message(
        b"\x00\x00" * 160,
        {"call_sid": "CA123", "caller": "+8613800001234"},
    )

    assert message["role"] == "user"
    assert message["content"][0]["type"] == "text"
    assert "不要要求系统先做语音转文字" in message["content"][0]["text"]
    assert message["content"][1]["type"] == "input_audio"
    audio_data = message["content"][1]["input_audio"]
    assert audio_data["format"] == "wav"
    assert audio_data["data"].startswith("data:audio/wav;base64,")

    wav_bytes = base64.b64decode(audio_data["data"].split(",", maxsplit=1)[1])
    with wave.open(BytesIO(wav_bytes), "rb") as wav:
        assert wav.getframerate() == 8000
        assert wav.getnchannels() == 1


def test_extract_assistant_text_delta_from_messages_tuple() -> None:
    part = StreamPart(
        event="messages",
        data=(
            {"type": "AIMessageChunk", "content": [{"type": "text", "text": "收到，"}]},
            {"langgraph_node": "agent"},
        ),
    )

    assert extract_assistant_text_delta(part) == "收到，"


def test_text_delta_segmenter_splits_on_phone_friendly_punctuation() -> None:
    segmenter = TextDeltaSegmenter(min_chars=3, max_chars=10)

    assert segmenter.push("收到，手机号") == ["收到，"]
    assert segmenter.push("方便留一下吗？") == ["手机号方便留一下吗？"]
    assert segmenter.flush() == []

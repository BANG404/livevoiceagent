import base64
import wave
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from langgraph_sdk.schema import StreamPart

from agent.domain import VisitorRegistration
from voice.agent_stream import (
    VOICE_TEXT_INSTRUCTION,
    build_audio_user_message,
    build_recent_visits_user_message,
    build_text_user_message,
    extract_assistant_text_delta,
)
import voice.app as voice_app_module
from voice.app import (
    TextDeltaSegmenter,
    _parse_custom_parameters,
    _recent_visits_for_caller,
    app,
)


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


def test_voice_webhook_returns_stream_without_twilio_say(monkeypatch) -> None:
    monkeypatch.setattr(
        voice_app_module,
        "settings",
        type(
            "SettingsStub",
            (),
            {
                "websocket_base_url": "wss://example.ngrok-free.app",
            },
        )(),
    )
    client = TestClient(app)

    response = client.post(
        "/voice", data={"CallSid": "CA123", "From": "+8613800001234"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Say" not in response.text
    assert (
        '<Connect><Stream url="wss://example.ngrok-free.app/twilio/media">'
        in response.text
    )
    assert '<Parameter name="call_sid" value="CA123" />' in response.text
    assert '<Parameter name="caller" value="+8613800001234" />' in response.text


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

    wav_bytes = base64.b64decode(
        audio_data["data"].removeprefix("data:audio/wav;base64,")
    )
    with wave.open(BytesIO(wav_bytes), "rb") as wav:
        assert wav.getframerate() == 8000
        assert wav.getnchannels() == 1


def test_build_recent_visits_user_message_embeds_last_five_visits() -> None:
    message = build_recent_visits_user_message(
        {"call_sid": "CA123", "caller": "+8613800001234"},
        [
            VisitorRegistration(
                plate_number="沪A12345",
                company="蓝色鲸鱼科技",
                phone="13800001234",
                reason="送货",
            )
        ],
    )

    assert message["role"] == "user"
    assert "近5次来访记录" in message["content"]
    assert "沪A12345" in message["content"]
    assert "请根据以下来电信息直接开始说第一句欢迎语" in message["content"]


def test_build_text_user_message_embeds_transcript_and_call_context() -> None:
    message = build_text_user_message(
        "我的车牌沪A12345，找蓝色鲸鱼科技送货。",
        {"call_sid": "CA123", "caller": "+8613800001234"},
    )

    assert message["role"] == "user"
    assert VOICE_TEXT_INSTRUCTION in message["content"]
    assert "来电号码：+8613800001234。" in message["content"]
    assert "Twilio CallSid：CA123。" in message["content"]
    assert (
        "访客本轮语音转写：我的车牌沪A12345，找蓝色鲸鱼科技送货。" in message["content"]
    )


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


@pytest.mark.anyio
async def test_recent_visits_for_caller_reads_store_async(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    monkeypatch.setattr(
        voice_app_module,
        "settings",
        type("SettingsStub", (), {"visitor_store_path": str(store_path)})(),
    )
    from agent.domain import VisitorStore

    VisitorStore(str(store_path)).append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="送货",
        )
    )

    recent = await _recent_visits_for_caller({"caller": "+86 13800001234"})

    assert len(recent) == 1
    assert recent[0].plate_number == "沪A12345"

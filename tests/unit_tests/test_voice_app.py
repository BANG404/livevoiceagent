import base64
import asyncio
import wave
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from langgraph_sdk.schema import StreamPart

from agent.domain import VisitorRegistration
from voice.agent_stream import (
    build_audio_user_message,
    build_recent_visits_user_message,
    build_text_user_message,
    extract_assistant_text_delta,
)
import voice.app as voice_app_module
from voice.app import (
    _CallState,
    _cancel_response_task,
    _handle_utterance,
    _parse_custom_parameters,
    _recent_visits_for_caller,
    _transcribe_utterance,
    app,
)
from voice.tts_pipeline import TextDeltaSegmenter


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
    assert "Twilio CallSid" not in message["content"][0]["text"]
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
    assert "Twilio CallSid" not in message["content"]


def test_build_text_user_message_embeds_transcript_and_call_context() -> None:
    message = build_text_user_message("我的车牌沪A12345，找蓝色鲸鱼科技送货。")

    assert message["role"] == "user"
    assert message["content"] == "我的车牌沪A12345，找蓝色鲸鱼科技送货。"


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

    # 。！？；are strong splits; ，is fallback-only, so the buffer waits for ？
    assert segmenter.push("收到，手机号") == []
    assert segmenter.push("方便留一下吗？") == ["收到，手机号方便留一下吗？"]
    assert segmenter.flush() == []


@pytest.mark.anyio
async def test_recent_visits_for_caller_reads_store_async(
    tmp_path, monkeypatch
) -> None:
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


@pytest.mark.anyio
async def test_transcribe_utterance_merges_segments_before_agent_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, str]] = []

        async def send_json(self, payload: dict[str, str]) -> None:
            self.events.append(payload)

    class FakeTts:
        async def stream_pcm16(self, text: str):
            yield b"\x01\x00" * 160

    class FakeAgent:
        uses_stt = True

        def __init__(self) -> None:
            self.transcripts = ["我的车牌沪A12345", "来送货"]
            self.reply_inputs: list[str] = []

        async def transcribe_utterance(self, pcm16: bytes) -> str:
            assert pcm16
            await asyncio.sleep(0.01)
            return self.transcripts.pop(0)

        async def stream_reply_from_text(
            self,
            thread_id: str,
            transcript: str,
            metadata: dict[str, str],
        ):
            assert thread_id == "thread-1"
            assert metadata["call_sid"] == "CA123"
            self.reply_inputs.append(transcript)
            yield f"收到：{transcript}"

    monkeypatch.setattr(voice_app_module, "TRANSCRIPT_MERGE_GRACE_SECONDS", 0.01)

    websocket = FakeWebSocket()
    agent = FakeAgent()
    tts = FakeTts()
    call_state = _CallState(user_speaking=True)
    metadata = {"call_sid": "CA123", "caller": "+8613800001234"}

    first_task = asyncio.create_task(
        _transcribe_utterance(
            websocket,
            "MZ123",
            b"\x01\x00" * 160,
            agent,
            "thread-1",
            tts,
            metadata,
            call_state,
        )
    )
    call_state.stt_tasks.add(first_task)
    await first_task

    assert agent.reply_inputs == []
    assert call_state.pending_transcripts == ["我的车牌沪A12345"]

    call_state.user_speaking = False
    second_task = asyncio.create_task(
        _transcribe_utterance(
            websocket,
            "MZ123",
            b"\x02\x00" * 160,
            agent,
            "thread-1",
            tts,
            metadata,
            call_state,
        )
    )
    call_state.stt_tasks.add(second_task)
    await second_task

    if call_state.flush_task is not None:
        await call_state.flush_task
    if call_state.response_task is not None:
        await call_state.response_task

    assert agent.reply_inputs == ["我的车牌沪A12345\n来送货"]
    assert call_state.pending_transcripts == []
    assert websocket.events


# ---------------------------------------------------------------------------
# _handle_utterance
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_utterance_skips_when_thread_id_is_empty() -> None:
    class FailAgent:
        uses_stt = False

        async def stream_reply_from_audio(self, *a, **kw):
            pytest.fail("agent should not be called")
            yield ""

    class FailTts:
        async def stream_pcm16(self, text: str):
            pytest.fail("TTS should not be called")
            yield b""

    class FailWebSocket:
        async def send_json(self, payload: dict) -> None:
            pytest.fail("websocket should not be called")

    call_state = _CallState()
    await _handle_utterance(
        FailWebSocket(), "MZ123", b"\x00" * 320, FailAgent(), "", FailTts(), {}, call_state
    )
    assert call_state.response_task is None
    assert call_state.stt_tasks == set()


@pytest.mark.anyio
async def test_handle_utterance_audio_mode_creates_response_task() -> None:
    class StubWebSocket:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.events.append(payload)

    class StubAgent:
        uses_stt = False

        async def stream_reply_from_audio(
            self, thread_id: str, pcm16: bytes, metadata: dict
        ):
            assert thread_id == "thread-1"
            yield "收到"

    class StubTts:
        async def stream_pcm16(self, text: str):
            yield b"\x01\x00" * 160

    call_state = _CallState()
    ws = StubWebSocket()
    await _handle_utterance(
        ws, "MZ123", b"\x00" * 320, StubAgent(), "thread-1", StubTts(), {}, call_state
    )

    assert call_state.response_task is not None
    await call_state.response_task
    assert call_state.stt_tasks == set()


@pytest.mark.anyio
async def test_handle_utterance_stt_mode_registers_stt_task() -> None:
    class StubAgent:
        uses_stt = True

        async def transcribe_utterance(self, pcm16: bytes) -> str:
            await asyncio.sleep(100)  # never completes during this test
            return ""

    class StubTts:
        async def stream_pcm16(self, text: str):
            yield b""

    class StubWebSocket:
        async def send_json(self, payload: dict) -> None:
            pass

    call_state = _CallState()
    await _handle_utterance(
        StubWebSocket(), "MZ123", b"\x00" * 320, StubAgent(), "thread-1", StubTts(), {}, call_state
    )

    assert len(call_state.stt_tasks) == 1
    tasks = list(call_state.stt_tasks)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# _cancel_response_task
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_response_task_returns_none_for_none_input() -> None:
    class StubWebSocket:
        async def send_json(self, payload: dict) -> None:
            pass

    result = await _cancel_response_task(None, StubWebSocket(), "MZ123")
    assert result is None


@pytest.mark.anyio
async def test_cancel_response_task_awaits_done_task_without_sending_clear() -> None:
    class StubWebSocket:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.events.append(payload)

    async def noop() -> None:
        pass

    task = asyncio.create_task(noop())
    await asyncio.sleep(0)
    assert task.done()

    ws = StubWebSocket()
    result = await _cancel_response_task(task, ws, "MZ123")

    assert result is None
    assert ws.events == []


@pytest.mark.anyio
async def test_cancel_response_task_cancels_live_task_and_sends_clear() -> None:
    class StubWebSocket:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.events.append(payload)

    cancelled_threads: list[str] = []

    class StubAgent:
        async def cancel_active_run(self, thread_id: str) -> None:
            cancelled_threads.append(thread_id)

    async def forever() -> None:
        await asyncio.sleep(100)

    task = asyncio.create_task(forever())
    ws = StubWebSocket()

    result = await _cancel_response_task(
        task, ws, "MZ123", agent=StubAgent(), thread_id="thread-1"
    )

    assert result is None
    assert task.cancelled()
    assert cancelled_threads == ["thread-1"]
    assert {"event": "clear", "streamSid": "MZ123"} in ws.events

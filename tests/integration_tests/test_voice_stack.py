import asyncio

import pytest

from agent.config import Settings, settings
import voice.app as voice_app_module
from voice.app import _CallState, _transcribe_utterance
from voice.audio import (
    FRAME_BYTES_PCM16,
    FRAME_SAMPLES,
    SileroVad,
    UtteranceBuffer,
    build_vad,
)
from voice.speech import KokoroTextToSpeech, build_stt, build_tts

pytestmark = pytest.mark.anyio


def _pcm_silence_frame() -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES


def _skip_unavailable_speech_roundtrip() -> None:
    if not settings.dashscope_api_key:
        pytest.skip(
            "Set DASHSCOPE_API_KEY to run speech round-trip integration tests.",
        )


def _frame_iter(pcm16: bytes) -> list[bytes]:
    frames: list[bytes] = []
    for offset in range(0, len(pcm16), FRAME_BYTES_PCM16):
        frame = pcm16[offset : offset + FRAME_BYTES_PCM16]
        if len(frame) < FRAME_BYTES_PCM16:
            frame = frame + (b"\x00" * (FRAME_BYTES_PCM16 - len(frame)))
        frames.append(frame)
    return frames


def _normalize_text(value: str) -> str:
    return "".join(char for char in value if not char.isspace())


def test_silero_vad_builds_real_detector_and_ignores_silence() -> None:
    vad = build_vad(provider="silero")

    assert isinstance(vad, SileroVad)

    for _ in range(32):
        assert vad.is_speech(_pcm_silence_frame()) is False

    vad.reset()

    assert vad.is_speech(_pcm_silence_frame()) is False


async def test_kokoro_tts_synthesizes_pcm16_with_default_repo() -> None:
    settings = Settings(
        tts_provider="kokoro",
        kokoro_lang_code="z",
        kokoro_repo_id="hexgrad/Kokoro-82M",
        agent_voice="zf_xiaobei",
    )

    tts = build_tts(settings)

    assert isinstance(tts, KokoroTextToSpeech)

    chunks = [chunk async for chunk in tts.stream_pcm16("您好，欢迎光临")]

    assert chunks
    assert all(isinstance(chunk, bytes) and len(chunk) > 0 for chunk in chunks)
    assert all(len(chunk) % 2 == 0 for chunk in chunks)
    assert any(any(byte != 0 for byte in chunk) for chunk in chunks)


async def test_tts_audio_roundtrip_vad_stt_merges_followup_before_agent_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_unavailable_speech_roundtrip()

    speech_settings = Settings(
        tts_provider="kokoro",
        kokoro_lang_code=settings.kokoro_lang_code,
        kokoro_repo_id=settings.kokoro_repo_id,
        agent_voice=settings.agent_voice,
        stt_provider="dashscope",
        dashscope_api_key=settings.dashscope_api_key,
        dashscope_base_url=settings.dashscope_base_url,
        dashscope_asr_model=settings.dashscope_asr_model,
        dashscope_asr_language=settings.dashscope_asr_language or "zh",
    )
    tts = build_tts(speech_settings)
    stt = build_stt(speech_settings)

    assert isinstance(tts, KokoroTextToSpeech)
    assert stt is not None

    utterance_buffer = UtteranceBuffer(
        vad=build_vad(
            provider="silero",
            threshold=0.35,
            min_silence_duration_ms=250,
        ),
        silence_frames_to_close=5,
        min_speech_frames=3,
        preroll_frames=6,
    )
    silence_frames = [_pcm_silence_frame() for _ in range(12)]
    first_pcm16 = b"".join([chunk async for chunk in tts.stream_pcm16("请登记来访")])
    second_pcm16 = b"".join([chunk async for chunk in tts.stream_pcm16("我是来送货的")])

    assert first_pcm16
    assert second_pcm16

    class FakeWebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.events.append(payload)

    class FakeReplyTts:
        async def stream_pcm16(self, text: str):
            assert text
            yield b"\x01\x00" * FRAME_SAMPLES

    class FakeAgent:
        uses_stt = True

        def __init__(self) -> None:
            self.raw_transcripts: list[str] = []
            self.reply_inputs: list[str] = []

        async def transcribe_utterance(self, pcm16: bytes) -> str:
            transcript = (await stt.transcribe_pcm16(pcm16)).strip()
            self.raw_transcripts.append(transcript)
            return transcript

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

    async def push_audio_until_utterance(
        pcm16: bytes,
        call_state: _CallState,
    ) -> bytes | None:
        utterance: bytes | None = None
        for frame in [*_frame_iter(pcm16), *silence_frames]:
            utterance = utterance_buffer.push(frame)
            if utterance_buffer.consume_speech_started():
                call_state.user_speaking = True
                call_state.flush_task = await voice_app_module._cancel_task(
                    call_state.flush_task
                )
            if utterance is not None:
                call_state.user_speaking = False
                return utterance
        return None

    monkeypatch.setattr(voice_app_module, "TRANSCRIPT_MERGE_GRACE_SECONDS", 0.5)

    websocket = FakeWebSocket()
    agent = FakeAgent()
    reply_tts = FakeReplyTts()
    call_state = _CallState()
    metadata = {"call_sid": "CA123", "caller": "+8613800001234"}

    first_utterance = await push_audio_until_utterance(first_pcm16, call_state)
    assert first_utterance is not None

    first_task = asyncio.create_task(
        _transcribe_utterance(
            websocket,
            "MZ123",
            first_utterance,
            agent,
            "thread-1",
            reply_tts,
            metadata,
            call_state,
        )
    )
    call_state.stt_tasks.add(first_task)

    second_utterance = await push_audio_until_utterance(second_pcm16, call_state)
    assert second_utterance is not None

    second_task = asyncio.create_task(
        _transcribe_utterance(
            websocket,
            "MZ123",
            second_utterance,
            agent,
            "thread-1",
            reply_tts,
            metadata,
            call_state,
        )
    )
    call_state.stt_tasks.add(second_task)

    await first_task
    await second_task

    if call_state.flush_task is not None:
        await call_state.flush_task
    if call_state.response_task is not None:
        await call_state.response_task

    assert len(agent.raw_transcripts) == 2
    assert len(agent.reply_inputs) == 1
    assert call_state.pending_transcripts == []
    assert websocket.events

    first_transcript = _normalize_text(agent.raw_transcripts[0])
    second_transcript = _normalize_text(agent.raw_transcripts[1])
    merged_transcript = _normalize_text(agent.reply_inputs[0])

    assert first_transcript
    assert second_transcript
    assert first_transcript in merged_transcript
    assert second_transcript in merged_transcript

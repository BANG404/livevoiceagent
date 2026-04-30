import sys
import types

import numpy as np
import pytest

from agent.config import Settings
from voice.speech import (
    KokoroTextToSpeech,
    SilenceTextToSpeech,
    TextToSpeech,
    _waveform_to_twilio_pcm16,
    build_tts,
    pcm16_wav_bytes,
)


@pytest.mark.anyio
async def test_text_to_speech_stream_pcm16_yields_synthesize_result() -> None:
    class FakeTTS(TextToSpeech):
        async def synthesize_pcm16(self, text: str) -> bytes:
            assert text == "hello"
            return b"abc"

    tts = FakeTTS()

    chunks = [chunk async for chunk in tts.stream_pcm16("hello")]

    assert chunks == [b"abc"]


@pytest.mark.anyio
async def test_silence_tts_uses_bounded_duration() -> None:
    tts = SilenceTextToSpeech()

    short = await tts.synthesize_pcm16("hi")
    long = await tts.synthesize_pcm16("x" * 100)

    assert len(short) == 8000 * 2 * 300 // 1000
    assert len(long) == 8000 * 2 * 1200 // 1000
    assert set(short) == {0}


def test_build_tts_falls_back_to_silence_when_kokoro_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_import = __import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "kokoro":
            raise ImportError("kokoro not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    caplog.set_level("ERROR")
    tts = build_tts(Settings(tts_provider="kokoro"))

    assert isinstance(tts, SilenceTextToSpeech)
    assert "Failed to initialize Kokoro TTS" in caplog.text


@pytest.mark.anyio
async def test_kokoro_tts_streams_resampled_pcm16_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePipeline:
        def __init__(self, *, lang_code: str, repo_id: str) -> None:
            self.lang_code = lang_code
            self.repo_id = repo_id
            self.calls: list[tuple[str, str]] = []

        def __call__(self, text: str, voice: str):
            self.calls.append((text, voice))
            yield (
                0,
                None,
                np.array([0.0, 0.5, -0.5, 1.0, -1.0, 0.25], dtype=np.float32),
            )
            yield (1, None, np.array([0.1, -0.1, 0.0], dtype=np.float32))

    fake_kokoro = types.SimpleNamespace(KPipeline=FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    settings = Settings(
        tts_provider="kokoro",
        kokoro_lang_code="z",
        kokoro_repo_id="repo/test",
        agent_voice="zf_xiaobei",
    )
    tts = KokoroTextToSpeech(settings)

    chunks = [chunk async for chunk in tts.stream_pcm16("您好")]

    assert len(chunks) == 2
    assert all(isinstance(chunk, bytes) and chunk for chunk in chunks)
    assert tts.pipeline.calls == [("您好", "zf_xiaobei")]


@pytest.mark.anyio
async def test_kokoro_tts_retries_with_default_voice_when_configured_voice_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePipeline:
        def __init__(self, *, lang_code: str, repo_id: str) -> None:
            self.calls: list[tuple[str, str]] = []

        def __call__(self, text: str, voice: str):
            self.calls.append((text, voice))
            if voice == "missing_voice":
                raise FileNotFoundError("voice asset not found")
            yield (0, None, np.array([0.0, 0.25, -0.25], dtype=np.float32))

    fake_kokoro = types.SimpleNamespace(KPipeline=FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    settings = Settings(
        tts_provider="kokoro",
        kokoro_lang_code="z",
        kokoro_repo_id="repo/test",
        agent_voice="missing_voice",
    )
    tts = KokoroTextToSpeech(settings)

    chunks = [chunk async for chunk in tts.stream_pcm16("您好")]

    assert len(chunks) == 1
    assert all(isinstance(chunk, bytes) and chunk for chunk in chunks)
    assert tts.pipeline.calls == [("您好", "missing_voice"), ("您好", "zf_xiaobei")]


def test_waveform_to_twilio_pcm16_resamples_from_24k_to_8k() -> None:
    waveform = np.linspace(-1.0, 1.0, 24, dtype=np.float32)

    pcm16 = _waveform_to_twilio_pcm16(waveform)

    assert len(pcm16) == 8 * 2


def test_pcm16_wav_bytes_wraps_audio_in_mono_8k_wav() -> None:
    wav_bytes = pcm16_wav_bytes(b"\x01\x00\x02\x00", sample_rate=8000)

    assert wav_bytes[:4] == b"RIFF"
    assert b"WAVE" in wav_bytes[:16]

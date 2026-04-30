import pytest

from agent.config import Settings
from voice.audio import FRAME_SAMPLES, SileroVad, build_vad
from voice.speech import KokoroTextToSpeech, build_tts

pytestmark = pytest.mark.anyio


def _pcm_silence_frame() -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES


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

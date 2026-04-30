"""Speech adapters for the voice transport layer.

The concrete adapters are intentionally thin. They keep Twilio streaming and
TTS replaceable while the visitor workflow stays stable.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from collections.abc import AsyncIterator

import numpy as np

from agent.config import Settings


logger = logging.getLogger(__name__)
DEFAULT_KOKORO_ZH_VOICE = "zf_xiaobei"
KOKORO_VOICE_ALIASES = {
    "zf_001": DEFAULT_KOKORO_ZH_VOICE,
}


def pcm16_wav_bytes(pcm16: bytes, sample_rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16)
    return buffer.getvalue()


class TextToSpeech:
    async def synthesize_pcm16(self, text: str) -> bytes:
        raise NotImplementedError

    async def stream_pcm16(self, text: str) -> AsyncIterator[bytes]:
        pcm16 = await self.synthesize_pcm16(text)
        if pcm16:
            yield pcm16


class SilenceTextToSpeech(TextToSpeech):
    """Fallback TTS that lets the server run before Kokoro is installed."""

    async def synthesize_pcm16(self, text: str) -> bytes:
        duration_ms = max(300, min(1200, len(text) * 60))
        samples = 8000 * duration_ms // 1000
        return b"\x00\x00" * samples


class KokoroTextToSpeech(TextToSpeech):
    def __init__(self, settings: Settings) -> None:
        from kokoro import KPipeline

        self.settings = settings
        self.pipeline = KPipeline(
            lang_code=settings.kokoro_lang_code,
            repo_id=settings.kokoro_repo_id,
        )

    async def synthesize_pcm16(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_pcm16_sync, text)

    async def stream_pcm16(self, text: str) -> AsyncIterator[bytes]:
        chunks = await asyncio.to_thread(self._synthesize_pcm16_chunks_sync, text)
        for chunk in chunks:
            if chunk:
                yield chunk

    def _synthesize_pcm16_sync(self, text: str) -> bytes:
        return b"".join(self._synthesize_pcm16_chunks_sync(text))

    def _synthesize_pcm16_chunks_sync(self, text: str) -> list[bytes]:
        voices = self._voice_candidates()
        last_error: Exception | None = None

        for index, voice in enumerate(voices):
            try:
                chunks: list[np.ndarray] = []
                for _, _, audio in self.pipeline(text, voice=voice):
                    if audio is not None:
                        chunks.append(np.asarray(audio, dtype=np.float32))
                if chunks:
                    return [_waveform_to_twilio_pcm16(waveform) for waveform in chunks]
            except Exception as exc:
                last_error = exc
                if index + 1 < len(voices):
                    logger.warning(
                        "Kokoro voice %r failed; retrying with %r.",
                        voice,
                        voices[index + 1],
                        exc_info=exc,
                    )
                    continue
                logger.exception("Kokoro synthesis failed for voice %r.", voice)

        if last_error is None:
            logger.warning("Kokoro returned no audio for voice %r.", voices[0])
        return []

    def _voice_candidates(self) -> list[str]:
        configured_voice = self.settings.agent_voice
        normalized_voice = KOKORO_VOICE_ALIASES.get(configured_voice, configured_voice)
        if normalized_voice != configured_voice:
            logger.warning(
                "Mapped legacy Kokoro voice %r to %r.",
                configured_voice,
                normalized_voice,
            )

        voices = [normalized_voice]
        if (
            self.settings.kokoro_lang_code == "z"
            and normalized_voice != DEFAULT_KOKORO_ZH_VOICE
        ):
            voices.append(DEFAULT_KOKORO_ZH_VOICE)
        return voices


def build_tts(settings: Settings) -> TextToSpeech:
    if settings.tts_provider == "kokoro":
        try:
            return KokoroTextToSpeech(settings)
        except Exception:
            logger.exception(
                "Failed to initialize Kokoro TTS; falling back to silence output."
            )
            return SilenceTextToSpeech()
    return SilenceTextToSpeech()


def _resample_linear(
    waveform: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    if source_rate == target_rate or waveform.size == 0:
        return waveform

    source_positions = np.arange(waveform.size)
    target_size = int(waveform.size * target_rate / source_rate)
    target_positions = np.linspace(0, waveform.size - 1, target_size)
    return np.interp(target_positions, source_positions, waveform).astype(np.float32)


def _waveform_to_twilio_pcm16(waveform: np.ndarray) -> bytes:
    waveform_8k = _resample_linear(waveform, 24000, 8000)
    waveform_8k = np.clip(waveform_8k, -1.0, 1.0)
    return (waveform_8k * 32767).astype("<i2").tobytes()

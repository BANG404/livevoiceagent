"""Speech adapters for the voice transport layer.

The concrete adapters are intentionally thin. They keep Twilio streaming,
transcription, and TTS replaceable while the visitor workflow stays stable.
"""

from __future__ import annotations

import io
import wave

import numpy as np
from openai import AsyncOpenAI

from agent.config import Settings


def pcm16_wav_bytes(pcm16: bytes, sample_rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16)
    return buffer.getvalue()


class SpeechToText:
    async def transcribe(self, pcm16: bytes) -> str:
        raise NotImplementedError


class OpenAISpeechToText(SpeechToText):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key or None)

    async def transcribe(self, pcm16: bytes) -> str:
        wav_bytes = pcm16_wav_bytes(pcm16)
        audio_file = ("speech.wav", wav_bytes, "audio/wav")
        result = await self.client.audio.transcriptions.create(
            model=self.settings.stt_model,
            file=audio_file,
            language="zh",
        )
        return result.text.strip()


class TextToSpeech:
    async def synthesize_pcm16(self, text: str) -> bytes:
        raise NotImplementedError


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
        self.pipeline = KPipeline(lang_code=settings.kokoro_lang_code)

    async def synthesize_pcm16(self, text: str) -> bytes:
        chunks: list[np.ndarray] = []
        for _, _, audio in self.pipeline(text, voice=self.settings.agent_voice):
            chunks.append(np.asarray(audio, dtype=np.float32))

        if not chunks:
            return b""

        waveform = np.concatenate(chunks)
        waveform_8k = _resample_linear(waveform, 24000, 8000)
        waveform_8k = np.clip(waveform_8k, -1.0, 1.0)
        return (waveform_8k * 32767).astype("<i2").tobytes()


def build_tts(settings: Settings) -> TextToSpeech:
    if settings.tts_provider == "kokoro":
        try:
            return KokoroTextToSpeech(settings)
        except ImportError:
            return SilenceTextToSpeech()
    return SilenceTextToSpeech()


def _resample_linear(waveform: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or waveform.size == 0:
        return waveform

    source_positions = np.arange(waveform.size)
    target_size = int(waveform.size * target_rate / source_rate)
    target_positions = np.linspace(0, waveform.size - 1, target_size)
    return np.interp(target_positions, source_positions, waveform).astype(np.float32)

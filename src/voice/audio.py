"""Audio helpers for Twilio Media Streams."""

from __future__ import annotations

import base64
import math
import struct
from collections import deque
from typing import Protocol

import numpy as np


TWILIO_SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_SAMPLES = TWILIO_SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES_MULAW = FRAME_SAMPLES
FRAME_BYTES_PCM16 = FRAME_SAMPLES * 2


def mulaw_payload_to_pcm16(payload: str) -> bytes:
    ulaw = base64.b64decode(payload)
    samples = [_mulaw_to_linear(byte) for byte in ulaw]
    return struct.pack("<" + "h" * len(samples), *samples)


def pcm16_to_mulaw_payload(pcm16: bytes) -> str:
    samples = struct.unpack(
        "<" + "h" * (len(pcm16) // 2), pcm16[: len(pcm16) - len(pcm16) % 2]
    )
    ulaw = bytes(_linear_to_mulaw(sample) for sample in samples)
    return base64.b64encode(ulaw).decode("ascii")


def rms_energy(pcm16: bytes) -> int:
    if not pcm16:
        return 0
    samples = struct.unpack(
        "<" + "h" * (len(pcm16) // 2), pcm16[: len(pcm16) - len(pcm16) % 2]
    )
    if not samples:
        return 0
    return int(math.sqrt(sum(sample * sample for sample in samples) / len(samples)))


def _linear_to_mulaw(sample: int) -> int:
    bias = 0x84
    clip = 32635
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample = min(sample, clip) + bias

    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        mask >>= 1
        exponent -= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _mulaw_to_linear(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


class VoiceActivityDetector(Protocol):
    def is_speech(self, pcm16: bytes) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError


class EnergyVad:
    """Small fallback VAD for tests and local demos.

    Production can swap this with SileroVad without changing the stream loop.
    """

    def __init__(self, threshold: int = 350) -> None:
        self.threshold = threshold

    def is_speech(self, pcm16: bytes) -> bool:
        return rms_energy(pcm16) >= self.threshold

    def reset(self) -> None:
        return None


class SileroVad:
    """Streaming Silero VAD wrapper for Twilio's 8 kHz PCM frames."""

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_duration_ms: int = 350,
        sample_rate: int = TWILIO_SAMPLE_RATE,
    ) -> None:
        from silero_vad import VADIterator, load_silero_vad
        import torch

        torch.set_num_threads(1)
        self.sample_rate = sample_rate
        self.window_samples = 256 if sample_rate == 8000 else 512
        self.window_bytes = self.window_samples * 2
        self._torch = torch
        self._iterator = VADIterator(
            load_silero_vad(),
            threshold=threshold,
            sampling_rate=sample_rate,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=30,
        )
        self._pending = bytearray()
        self._active = False

    def is_speech(self, pcm16: bytes) -> bool:
        self._pending.extend(pcm16)

        while len(self._pending) >= self.window_bytes:
            chunk = bytes(self._pending[: self.window_bytes])
            del self._pending[: self.window_bytes]
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768.0
            event = self._iterator(
                self._torch.from_numpy(samples), return_seconds=False
            )
            if not event:
                continue
            if "start" in event:
                self._active = True
            if "end" in event:
                self._active = False

        return self._active

    def reset(self) -> None:
        self._pending.clear()
        self._active = False
        self._iterator.reset_states()


def build_vad(
    provider: str = "silero",
    threshold: float = 0.5,
    min_silence_duration_ms: int = 350,
) -> VoiceActivityDetector:
    if provider == "silero":
        try:
            return SileroVad(
                threshold=threshold,
                min_silence_duration_ms=min_silence_duration_ms,
            )
        except ImportError:
            return EnergyVad()
    return EnergyVad()


class UtteranceBuffer:
    def __init__(
        self,
        vad: VoiceActivityDetector | None = None,
        silence_frames_to_close: int = 25,
        min_speech_frames: int = 8,
        preroll_frames: int = 6,
    ) -> None:
        self.vad = vad or EnergyVad()
        self.silence_frames_to_close = silence_frames_to_close
        self.min_speech_frames = min_speech_frames
        self.preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.frames: list[bytes] = []
        self.speech_frames = 0
        self.silence_frames = 0
        self.turn_open = False
        self._speech_started = False

    def push(self, pcm16: bytes) -> bytes | None:
        speaking = self.vad.is_speech(pcm16)
        if speaking:
            if not self.frames and self.preroll:
                self.frames.extend(self.preroll)
            self.speech_frames += 1
            self.silence_frames = 0
            self.frames.append(pcm16)
            if not self.turn_open and self.speech_frames >= self.min_speech_frames:
                self.turn_open = True
                self._speech_started = True
            return None

        self.preroll.append(pcm16)

        if self.frames:
            self.silence_frames += 1
            self.frames.append(pcm16)

        if (
            self.frames
            and self.speech_frames >= self.min_speech_frames
            and self.silence_frames >= self.silence_frames_to_close
        ):
            utterance = b"".join(self.frames)
            self.reset()
            return utterance

        if (
            self.frames
            and self.speech_frames < self.min_speech_frames
            and self.silence_frames >= self.silence_frames_to_close
        ):
            self.reset()

        return None

    def consume_speech_started(self) -> bool:
        started = self._speech_started
        self._speech_started = False
        return started

    def reset(self) -> None:
        self.frames = []
        self.speech_frames = 0
        self.silence_frames = 0
        self.preroll.clear()
        self.turn_open = False
        self._speech_started = False
        self.vad.reset()

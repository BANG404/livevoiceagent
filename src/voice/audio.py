"""Audio helpers for Twilio Media Streams."""

from __future__ import annotations

import base64
import math
import struct


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
    samples = struct.unpack("<" + "h" * (len(pcm16) // 2), pcm16[: len(pcm16) - len(pcm16) % 2])
    ulaw = bytes(_linear_to_mulaw(sample) for sample in samples)
    return base64.b64encode(ulaw).decode("ascii")


def rms_energy(pcm16: bytes) -> int:
    if not pcm16:
        return 0
    samples = struct.unpack("<" + "h" * (len(pcm16) // 2), pcm16[: len(pcm16) - len(pcm16) % 2])
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


class EnergyVad:
    """Small fallback VAD for tests and local demos.

    Production can swap this with SileroVad without changing the stream loop.
    """

    def __init__(self, threshold: int = 350) -> None:
        self.threshold = threshold

    def is_speech(self, pcm16: bytes) -> bool:
        return rms_energy(pcm16) >= self.threshold


class UtteranceBuffer:
    def __init__(
        self,
        vad: EnergyVad | None = None,
        silence_frames_to_close: int = 25,
        min_speech_frames: int = 8,
    ) -> None:
        self.vad = vad or EnergyVad()
        self.silence_frames_to_close = silence_frames_to_close
        self.min_speech_frames = min_speech_frames
        self.frames: list[bytes] = []
        self.speech_frames = 0
        self.silence_frames = 0

    def push(self, pcm16: bytes) -> bytes | None:
        speaking = self.vad.is_speech(pcm16)
        if speaking:
            self.speech_frames += 1
            self.silence_frames = 0
            self.frames.append(pcm16)
            return None

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

        if self.frames and self.speech_frames < self.min_speech_frames and self.silence_frames >= self.silence_frames_to_close:
            self.reset()

        return None

    def reset(self) -> None:
        self.frames = []
        self.speech_frames = 0
        self.silence_frames = 0

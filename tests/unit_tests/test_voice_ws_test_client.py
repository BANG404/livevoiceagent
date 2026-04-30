import wave
from pathlib import Path

import numpy as np

from voice.audio import FRAME_BYTES_PCM16, TWILIO_SAMPLE_RATE, mulaw_payload_to_pcm16
from voice.ws_test_client import (
    build_media_event,
    iter_pcm16_frames,
    load_wav_pcm16,
)


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.astype("<i2").tobytes())


def test_iter_pcm16_frames_zero_pads_last_chunk() -> None:
    pcm16 = b"\x01\x00" * 10

    frames = list(iter_pcm16_frames(pcm16, frame_bytes=32))

    assert len(frames) == 1
    assert len(frames[0]) == 32
    assert frames[0][: len(pcm16)] == pcm16
    assert frames[0][len(pcm16) :] == b"\x00" * (32 - len(pcm16))


def test_build_media_event_round_trips_pcm16() -> None:
    pcm16 = b"\x02\x00" * (FRAME_BYTES_PCM16 // 2)

    event = build_media_event("MZ123", pcm16)

    assert event["event"] == "media"
    assert event["streamSid"] == "MZ123"
    assert mulaw_payload_to_pcm16(event["media"]["payload"])


def test_load_wav_pcm16_downmixes_and_resamples(tmp_path: Path) -> None:
    samples = int(24000 * 0.1)
    left = np.full(samples, 1000, dtype=np.int16)
    right = np.full(samples, -1000, dtype=np.int16)
    stereo = np.column_stack([left, right]).reshape(-1)
    wav_path = tmp_path / "stereo.wav"
    _write_wav(wav_path, stereo, sample_rate=24000, channels=2)

    pcm16 = load_wav_pcm16(wav_path)

    expected_samples = int(TWILIO_SAMPLE_RATE * 0.1)
    assert len(pcm16) == expected_samples * 2

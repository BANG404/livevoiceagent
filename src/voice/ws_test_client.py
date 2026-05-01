"""Utilities for locally testing the Twilio-style voice websocket."""

from __future__ import annotations

import argparse
import asyncio
import json
import wave
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from websockets.asyncio.client import connect

from voice.audio import (
    FRAME_BYTES_PCM16,
    TWILIO_SAMPLE_RATE,
    mulaw_payload_to_pcm16,
    pcm16_to_mulaw_payload,
)


def load_wav_pcm16(
    path: str | Path,
    target_sample_rate: int = TWILIO_SAMPLE_RATE,
) -> bytes:
    """Load a WAV file and convert it into mono PCM16 for the websocket flow."""

    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise ValueError(f"{path} must be a 16-bit PCM WAV file")

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if sample_rate != target_sample_rate and samples.size:
        source_positions = np.arange(samples.size, dtype=np.float32)
        target_size = int(samples.size * target_sample_rate / sample_rate)
        target_positions = np.linspace(0, samples.size - 1, target_size)
        samples = np.interp(target_positions, source_positions, samples)

    samples = np.clip(samples, -32768, 32767).astype("<i2")
    return samples.tobytes()


def iter_pcm16_frames(
    pcm16: bytes,
    frame_bytes: int = FRAME_BYTES_PCM16,
) -> Iterable[bytes]:
    """Split PCM16 into Twilio-sized 20 ms frames and zero-pad the tail."""

    for offset in range(0, len(pcm16), frame_bytes):
        chunk = pcm16[offset : offset + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk += b"\x00" * (frame_bytes - len(chunk))
        yield chunk


def build_start_event(
    stream_sid: str,
    call_sid: str,
    caller: str,
) -> dict[str, Any]:
    return {
        "event": "start",
        "start": {
            "streamSid": stream_sid,
            "customParameters": {
                "call_sid": call_sid,
                "caller": caller,
            },
        },
    }


def build_media_event(stream_sid: str, pcm16_chunk: bytes) -> dict[str, Any]:
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": pcm16_to_mulaw_payload(pcm16_chunk)},
    }


def build_stop_event(stream_sid: str) -> dict[str, Any]:
    return {"event": "stop", "streamSid": stream_sid}


def write_pcm16_wav(
    path: str | Path,
    pcm16: bytes,
    sample_rate: int = TWILIO_SAMPLE_RATE,
) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16)


async def run_probe(
    url: str,
    wav_paths: Sequence[str | Path],
    caller: str = "+8613800001234",
    call_sid: str = "CAWSLOCALTEST",
    stream_sid: str = "MZWSLOCALTEST",
    tail_silence_ms: int = 800,
    receive_idle_ms: int = 1800,
    pace_ms: int = 20,
    output_wav: str | Path | None = None,
) -> bytes:
    """Send one or more user turns to the websocket and collect assistant audio."""

    silence_frame = b"\x00" * FRAME_BYTES_PCM16
    silence_frames = max(1, tail_silence_ms // 20)
    assistant_audio = bytearray()

    async with connect(url, max_size=None) as websocket:
        await websocket.send(
            json.dumps(
                build_start_event(stream_sid, call_sid, caller), ensure_ascii=False
            )
        )
        print(f"connected: {url}")
        print(f"start sent: call_sid={call_sid} caller={caller}")

        for index, wav_path in enumerate(wav_paths, start=1):
            pcm16 = load_wav_pcm16(wav_path)
            frame_count = 0

            print(f"turn {index}: sending {wav_path}")
            for frame in iter_pcm16_frames(pcm16):
                await websocket.send(
                    json.dumps(build_media_event(stream_sid, frame), ensure_ascii=False)
                )
                frame_count += 1
                if pace_ms > 0:
                    await asyncio.sleep(pace_ms / 1000)

            for _ in range(silence_frames):
                await websocket.send(
                    json.dumps(
                        build_media_event(stream_sid, silence_frame), ensure_ascii=False
                    )
                )
                if pace_ms > 0:
                    await asyncio.sleep(pace_ms / 1000)

            print(f"turn {index}: sent {frame_count} speech frames")
            reply_audio = await _receive_until_idle(
                websocket,
                receive_idle_ms=receive_idle_ms,
            )
            assistant_audio.extend(reply_audio)
            print(
                f"turn {index}: received {len(reply_audio) // FRAME_BYTES_PCM16} reply frames"
            )

        await websocket.send(
            json.dumps(build_stop_event(stream_sid), ensure_ascii=False)
        )
        print("stop sent")

    if output_wav:
        write_pcm16_wav(output_wav, bytes(assistant_audio))
        print(f"assistant audio saved: {output_wav}")

    return bytes(assistant_audio)


async def _receive_until_idle(
    websocket: Any,
    receive_idle_ms: int,
) -> bytes:
    collected = bytearray()

    while True:
        try:
            raw = await asyncio.wait_for(
                websocket.recv(),
                timeout=receive_idle_ms / 1000,
            )
        except TimeoutError:
            break

        event = json.loads(raw)
        event_type = event.get("event")
        if event_type == "media":
            payload = event.get("media", {}).get("payload", "")
            collected.extend(mulaw_payload_to_pcm16(payload))
            print(f"recv media: {len(payload)} b64 chars")
        else:
            print(f"recv event: {event_type}")

    return bytes(collected)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local websocket probe for the Twilio-style voice flow.",
    )
    parser.add_argument(
        "wav_files",
        nargs="+",
        help="One or more 16-bit PCM WAV files to send as user turns.",
    )
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8000/twilio/media",
        help="WebSocket endpoint to probe.",
    )
    parser.add_argument(
        "--caller",
        default="+8613800001234",
        help="Caller number passed in customParameters.",
    )
    parser.add_argument(
        "--call-sid",
        default="CAWSLOCALTEST",
        help="CallSid passed in customParameters.",
    )
    parser.add_argument(
        "--stream-sid",
        default="MZWSLOCALTEST",
        help="streamSid used in websocket events.",
    )
    parser.add_argument(
        "--tail-silence-ms",
        type=int,
        default=800,
        help="Silence appended after each turn so the VAD can close the utterance.",
    )
    parser.add_argument(
        "--receive-idle-ms",
        type=int,
        default=1800,
        help="How long to wait after the last reply frame before considering a turn done.",
    )
    parser.add_argument(
        "--pace-ms",
        type=int,
        default=20,
        help="Delay between frames to mimic realtime sending. Use 0 for burst mode.",
    )
    parser.add_argument(
        "--output-wav",
        help="Optional output WAV file for the assistant audio.",
    )
    return parser.parse_args(argv)


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    await run_probe(
        url=args.url,
        wav_paths=args.wav_files,
        caller=args.caller,
        call_sid=args.call_sid,
        stream_sid=args.stream_sid,
        tail_silence_ms=args.tail_silence_ms,
        receive_idle_ms=args.receive_idle_ms,
        pace_ms=args.pace_ms,
        output_wav=args.output_wav,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


__all__ = [
    "build_media_event",
    "build_start_event",
    "build_stop_event",
    "iter_pcm16_frames",
    "load_wav_pcm16",
    "main",
    "parse_args",
    "run_probe",
    "write_pcm16_wav",
]

"""TTS pipeline: text-delta segmentation and audio streaming to Twilio."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import WebSocket

from voice.audio import pcm16_to_mulaw_payload
from voice.speech import TextToSpeech


class TextDeltaSegmenter:
    def __init__(self, min_chars: int = 14, max_chars: int = 72) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.buffer = ""

    def push(self, delta: str) -> list[str]:
        self.buffer += delta
        ready: list[str] = []

        while self.buffer:
            split_at = self._split_index()
            if split_at <= 0:
                break
            ready.append(self.buffer[:split_at].strip())
            self.buffer = self.buffer[split_at:].lstrip()

        return [item for item in ready if item]

    def flush(self) -> list[str]:
        text = self.buffer.strip()
        self.buffer = ""
        return [text] if text else []

    def _split_index(self) -> int:
        # Strong punctuation: emit immediately once min_chars reached.
        strong = "。！？!?；;"
        # Weak punctuation: prefer over a bare hard cut, but only as fallback.
        weak = "，,、"
        for index, char in enumerate(self.buffer):
            if char in strong and index + 1 >= self.min_chars:
                return index + 1

        if len(self.buffer) < self.max_chars:
            return 0

        scan_end = min(len(self.buffer), self.max_chars)
        # Prefer a weak-punctuation boundary over a raw hard cut.
        for index in range(scan_end - 1, self.min_chars, -1):
            if self.buffer[index] in weak:
                return index + 1
        # English: land on whitespace when available.
        for index in range(scan_end - 1, self.min_chars, -1):
            if self.buffer[index].isspace():
                return index + 1
        return self.max_chars


async def stream_agent_reply(
    websocket: WebSocket,
    stream_sid: str,
    text_stream: AsyncIterator[str],
    tts: TextToSpeech,
) -> None:
    segmenter = TextDeltaSegmenter()
    async for segment in _tts_segments(text_stream, tts, segmenter):
        await _send_audio(websocket, stream_sid, segment)


async def single_text_reply(text: str) -> AsyncIterator[str]:
    yield text


async def _tts_segments(
    text_stream: AsyncIterator[str],
    tts: TextToSpeech,
    segmenter: TextDeltaSegmenter,
) -> AsyncIterator[bytes]:
    async for delta in text_stream:
        for text in segmenter.push(delta):
            async for pcm16 in tts.stream_pcm16(text):
                yield pcm16

    for text in segmenter.flush():
        async for pcm16 in tts.stream_pcm16(text):
            yield pcm16


async def _send_audio(websocket: WebSocket, stream_sid: str, pcm16: bytes) -> None:
    if not stream_sid:
        return

    frame_size = 8000 * 2 // 50
    for offset in range(0, len(pcm16), frame_size):
        payload = pcm16_to_mulaw_payload(pcm16[offset : offset + frame_size])
        await websocket.send_json(
            {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            }
        )
        await asyncio.sleep(0.02)

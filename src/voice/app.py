"""FastAPI app for Twilio Voice webhooks and media streams."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any, Coroutine

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from agent.config import settings
from agent.domain import VisitorStore
from voice.agent_stream import LangGraphAudioAgent
from voice.audio import (
    UtteranceBuffer,
    build_vad,
    mulaw_payload_to_pcm16,
    pcm16_to_mulaw_payload,
)
from voice.speech import TextToSpeech, build_tts

app = FastAPI(title="Live Voice Visitor Agent")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/voice", methods=["GET", "POST"])
async def voice_webhook(request: Request) -> Response:
    form = await request.form() if request.method == "POST" else {}
    call_sid = form.get("CallSid", "")
    caller = form.get("From", "")

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=f"{settings.websocket_base_url}/twilio/media")
    stream.parameter(name="call_sid", value=str(call_sid))
    stream.parameter(name="caller", value=str(caller))
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/twilio/media")
async def twilio_media(websocket: WebSocket) -> None:
    await websocket.accept()
    stream_sid = ""
    metadata: dict[str, str] = {}
    utterances = UtteranceBuffer(
        vad=build_vad(
            provider=settings.vad_provider,
            threshold=settings.silero_vad_threshold,
            min_silence_duration_ms=settings.silero_vad_min_silence_ms,
        ),
        silence_frames_to_close=5 if settings.vad_provider == "silero" else 25,
    )
    tts = build_tts(settings)
    agent = LangGraphAudioAgent(settings)
    thread_id = ""
    response_task: asyncio.Task[None] | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            event: dict[str, Any] = json.loads(raw)
            event_type = event.get("event")

            if event_type == "start":
                stream_sid = event["start"]["streamSid"]
                metadata = _parse_custom_parameters(
                    event["start"].get("customParameters", {})
                )
                thread_id = await agent.create_thread(metadata)
                recent_visits = await _recent_visits_for_caller(metadata)
                response_task = await _replace_response_task(
                    response_task,
                    _stream_agent_reply(
                        websocket,
                        stream_sid,
                        agent.stream_welcome_text(thread_id, metadata, recent_visits),
                        tts,
                    ),
                )
                continue

            if event_type == "media":
                pcm16 = mulaw_payload_to_pcm16(event["media"]["payload"])
                utterance = utterances.push(pcm16)
                if utterances.consume_speech_started():
                    response_task = await _cancel_response_task(
                        response_task,
                        websocket,
                        stream_sid,
                        agent=agent,
                        thread_id=thread_id,
                    )
                if utterance:
                    response_task = await _replace_response_task(
                        response_task,
                        _handle_utterance(
                            websocket,
                            stream_sid,
                            utterance,
                            agent,
                            thread_id,
                            tts,
                            metadata,
                        ),
                    )
                continue

            if event_type == "stop":
                break
    except WebSocketDisconnect:
        return
    finally:
        await _cancel_response_task(
            response_task,
            websocket,
            stream_sid,
            agent=agent,
            thread_id=thread_id,
        )
        await agent.aclose()


async def _handle_utterance(
    websocket: WebSocket,
    stream_sid: str,
    pcm16: bytes,
    agent: LangGraphAudioAgent,
    thread_id: str,
    tts: TextToSpeech,
    metadata: dict[str, str],
) -> None:
    if not thread_id:
        return

    await _stream_agent_reply(
        websocket,
        stream_sid,
        agent.stream_reply_text(thread_id, pcm16, metadata),
        tts,
    )


async def _stream_agent_reply(
    websocket: WebSocket,
    stream_sid: str,
    text_stream: AsyncIterator[str],
    tts: TextToSpeech,
) -> None:
    segmenter = TextDeltaSegmenter()
    async for segment in _tts_segments(text_stream, tts, segmenter):
        await _send_audio(websocket, stream_sid, segment)


async def _recent_visits_for_caller(metadata: dict[str, str]) -> list[Any]:
    caller = metadata.get("caller", "").strip()
    if not caller:
        return []
    return await VisitorStore.recent_by_phone_async(
        settings.visitor_store_path,
        caller,
        limit=5,
    )


async def _replace_response_task(
    current: asyncio.Task[None] | None,
    coro: Coroutine[Any, Any, None],
) -> asyncio.Task[None]:
    if current is not None:
        if current.done():
            await _await_response_task(current)
        else:
            current.cancel()
            await _await_response_task(current)
    return asyncio.create_task(coro)


async def _cancel_response_task(
    task: asyncio.Task[None] | None,
    websocket: WebSocket,
    stream_sid: str,
    *,
    agent: LangGraphAudioAgent | None = None,
    thread_id: str = "",
) -> asyncio.Task[None] | None:
    if task is None:
        return None
    if task.done():
        await _await_response_task(task)
        return None

    if agent is not None and thread_id:
        with contextlib.suppress(Exception):
            await agent.cancel_active_run(thread_id)
    task.cancel()
    await _await_response_task(task)
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await _send_clear(websocket, stream_sid)
    return None


async def _await_response_task(task: asyncio.Task[None]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _send_clear(websocket: WebSocket, stream_sid: str) -> None:
    if not stream_sid:
        return
    await websocket.send_json({"event": "clear", "streamSid": stream_sid})


def _parse_custom_parameters(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}

    if isinstance(value, list):
        return {
            str(item["name"]): str(item.get("value", ""))
            for item in value
            if isinstance(item, dict) and "name" in item
        }

    return {}


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


async def _tts_segments(
    text_stream: AsyncIterator[str],
    tts: TextToSpeech,
    segmenter: "TextDeltaSegmenter",
) -> AsyncIterator[bytes]:
    async for delta in text_stream:
        for text in segmenter.push(delta):
            async for pcm16 in tts.stream_pcm16(text):
                yield pcm16

    for text in segmenter.flush():
        async for pcm16 in tts.stream_pcm16(text):
            yield pcm16


class TextDeltaSegmenter:
    def __init__(self, min_chars: int = 14, max_chars: int = 48) -> None:
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
        punctuation = "。！？!?；;，,"
        for index, char in enumerate(self.buffer):
            if char in punctuation and index + 1 >= self.min_chars:
                return index + 1

        if len(self.buffer) < self.max_chars:
            return 0

        for index in range(
            min(len(self.buffer), self.max_chars) - 1, self.min_chars, -1
        ):
            if self.buffer[index].isspace():
                return index + 1
        return self.max_chars

"""FastAPI app for Twilio Voice webhooks and media streams."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
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
)
from voice.speech import TextToSpeech, build_tts
from voice.tts_pipeline import TextDeltaSegmenter, single_text_reply, stream_agent_reply

logger = logging.getLogger(__name__)

app = FastAPI(title="Live Voice Visitor Agent")
TRANSCRIPT_MERGE_GRACE_SECONDS = 0.6


@dataclass
class _CallState:
    response_task: asyncio.Task[None] | None = None
    flush_task: asyncio.Task[None] | None = None
    stt_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    pending_transcripts: list[str] = field(default_factory=list)
    transcription_failed: bool = False
    user_speaking: bool = False


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
    call_state = _CallState()

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
                call_state.response_task = await _replace_response_task(
                    call_state.response_task,
                    stream_agent_reply(
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
                    call_state.user_speaking = True
                    call_state.flush_task = await _cancel_task(call_state.flush_task)
                    call_state.response_task = await _cancel_response_task(
                        call_state.response_task,
                        websocket,
                        stream_sid,
                        agent=agent,
                        thread_id=thread_id,
                    )
                if utterance:
                    call_state.user_speaking = False
                    await _handle_utterance(
                        websocket,
                        stream_sid,
                        utterance,
                        agent,
                        thread_id,
                        tts,
                        metadata,
                        call_state,
                    )
                continue

            if event_type == "stop":
                break
    except WebSocketDisconnect:
        return
    finally:
        call_state.flush_task = await _cancel_task(call_state.flush_task)
        await _cancel_stt_tasks(call_state)
        await _cancel_response_task(
            call_state.response_task,
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
    call_state: _CallState,
) -> None:
    if not thread_id:
        return

    if not agent.uses_stt:
        call_state.response_task = await _replace_response_task(
            call_state.response_task,
            stream_agent_reply(
                websocket,
                stream_sid,
                agent.stream_reply_from_audio(thread_id, pcm16, metadata),
                tts,
            ),
        )
        return

    task = asyncio.create_task(
        _transcribe_utterance(
            websocket,
            stream_sid,
            pcm16,
            agent,
            thread_id,
            tts,
            metadata,
            call_state,
        )
    )
    call_state.stt_tasks.add(task)


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


async def _cancel_task(
    task: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    if task is None:
        return None
    if not task.done():
        task.cancel()
    await _await_response_task(task)
    return None


async def _cancel_stt_tasks(call_state: _CallState) -> None:
    tasks = list(call_state.stt_tasks)
    call_state.stt_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        await _await_response_task(task)


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


async def _transcribe_utterance(
    websocket: WebSocket,
    stream_sid: str,
    pcm16: bytes,
    agent: LangGraphAudioAgent,
    thread_id: str,
    tts: TextToSpeech,
    metadata: dict[str, str],
    call_state: _CallState,
) -> None:
    try:
        transcript = await agent.transcribe_utterance(pcm16)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("STT failed")
        call_state.transcription_failed = True
    else:
        if transcript:
            call_state.pending_transcripts.append(transcript)
        else:
            call_state.transcription_failed = True
    finally:
        current_task = asyncio.current_task()
        if current_task is not None:
            call_state.stt_tasks.discard(current_task)

    await _schedule_pending_reply(
        websocket,
        stream_sid,
        agent,
        thread_id,
        tts,
        metadata,
        call_state,
    )


async def _schedule_pending_reply(
    websocket: WebSocket,
    stream_sid: str,
    agent: LangGraphAudioAgent,
    thread_id: str,
    tts: TextToSpeech,
    metadata: dict[str, str],
    call_state: _CallState,
) -> None:
    call_state.flush_task = await _cancel_task(call_state.flush_task)
    if call_state.user_speaking or call_state.stt_tasks:
        return
    if not call_state.pending_transcripts and not call_state.transcription_failed:
        return

    call_state.flush_task = asyncio.create_task(
        _flush_pending_reply(
            websocket,
            stream_sid,
            agent,
            thread_id,
            tts,
            metadata,
            call_state,
        )
    )


async def _flush_pending_reply(
    websocket: WebSocket,
    stream_sid: str,
    agent: LangGraphAudioAgent,
    thread_id: str,
    tts: TextToSpeech,
    metadata: dict[str, str],
    call_state: _CallState,
) -> None:
    await asyncio.sleep(TRANSCRIPT_MERGE_GRACE_SECONDS)
    if call_state.user_speaking or call_state.stt_tasks:
        return

    if call_state.pending_transcripts:
        merged_transcript = "\n".join(call_state.pending_transcripts)
        call_state.pending_transcripts.clear()
        call_state.transcription_failed = False
        call_state.response_task = await _replace_response_task(
            call_state.response_task,
            stream_agent_reply(
                websocket,
                stream_sid,
                agent.stream_reply_from_text(thread_id, merged_transcript, metadata),
                tts,
            ),
        )
        return

    if call_state.transcription_failed:
        call_state.transcription_failed = False
        call_state.response_task = await _replace_response_task(
            call_state.response_task,
            stream_agent_reply(
                websocket,
                stream_sid,
                single_text_reply("抱歉，刚才没听清，请再说一遍。"),
                tts,
            ),
        )


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



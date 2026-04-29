"""FastAPI app for Twilio Voice webhooks and media streams."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from agent.config import settings
from agent.graph import graph
from voice.audio import UtteranceBuffer, mulaw_payload_to_pcm16, pcm16_to_mulaw_payload
from voice.speech import OpenAISpeechToText, SpeechToText, TextToSpeech, build_tts

load_dotenv()

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
    utterances = UtteranceBuffer()
    stt = OpenAISpeechToText(settings)
    tts = build_tts(settings)
    transcript: list[tuple[str, str]] = []

    try:
        while True:
            raw = await websocket.receive_text()
            event: dict[str, Any] = json.loads(raw)
            event_type = event.get("event")

            if event_type == "start":
                stream_sid = event["start"]["streamSid"]
                metadata = _parse_custom_parameters(event["start"].get("customParameters", {}))
                await _send_audio(websocket, stream_sid, await tts.synthesize_pcm16("您好，请问车牌号多少，今天找哪家公司，什么事儿？"))
                continue

            if event_type == "media":
                pcm16 = mulaw_payload_to_pcm16(event["media"]["payload"])
                utterance = utterances.push(pcm16)
                if utterance:
                    await _handle_utterance(websocket, stream_sid, utterance, transcript, stt, tts, metadata)
                continue

            if event_type == "stop":
                break
    except WebSocketDisconnect:
        return


async def _handle_utterance(
    websocket: WebSocket,
    stream_sid: str,
    pcm16: bytes,
    transcript: list[tuple[str, str]],
    stt: SpeechToText,
    tts: TextToSpeech,
    metadata: dict[str, str],
) -> None:
    user_text = await stt.transcribe(pcm16)
    if not user_text:
        return

    transcript.append(("user", user_text))
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": role,
                    "content": content,
                }
                for role, content in transcript
            ],
            "call_sid": metadata.get("call_sid"),
            "caller": metadata.get("caller"),
        }
    )
    assistant_text = str(result["messages"][-1].content)
    transcript.append(("assistant", assistant_text))
    await _send_audio(websocket, stream_sid, await tts.synthesize_pcm16(assistant_text))


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

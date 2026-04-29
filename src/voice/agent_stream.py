"""LangGraph SDK streaming client for Twilio audio turns."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Mapping
from typing import Any

from langgraph_sdk import get_client
from langgraph_sdk.client import LangGraphClient
from langgraph_sdk.schema import StreamPart

from agent.config import Settings
from voice.speech import pcm16_wav_bytes


VOICE_AUDIO_INSTRUCTION = (
    "这是一段访客电话语音。请直接理解音频内容并继续完成园区访客登记；"
    "不要要求系统先做语音转文字。回复要短、自然、适合直接转成电话语音。"
)


def build_audio_user_message(
    pcm16: bytes,
    metadata: Mapping[str, str] | None = None,
    sample_rate: int = 8000,
) -> dict[str, Any]:
    metadata = metadata or {}
    context_parts = [VOICE_AUDIO_INSTRUCTION]
    if caller := metadata.get("caller"):
        context_parts.append(f"来电号码：{caller}。")
    if call_sid := metadata.get("call_sid"):
        context_parts.append(f"Twilio CallSid：{call_sid}。")

    audio_b64 = base64.b64encode(
        pcm16_wav_bytes(pcm16, sample_rate=sample_rate)
    ).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "".join(context_parts)},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": f"data:audio/wav;base64,{audio_b64}",
                    "format": "wav",
                },
            },
        ],
    }


class LangGraphAudioAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: LangGraphClient = get_client(
            url=settings.langgraph_api_url,
            api_key=settings.langgraph_api_key or None,
        )

    async def create_thread(self, metadata: Mapping[str, str]) -> str:
        thread = await self.client.threads.create(
            metadata={
                "call_sid": metadata.get("call_sid", ""),
                "caller": metadata.get("caller", ""),
            },
            graph_id=self.settings.langgraph_assistant_id,
        )
        return str(thread["thread_id"])

    async def stream_reply_text(
        self,
        thread_id: str,
        pcm16: bytes,
        metadata: Mapping[str, str],
    ) -> AsyncIterator[str]:
        async for part in self.client.runs.stream(
            thread_id=thread_id,
            assistant_id=self.settings.langgraph_assistant_id,
            input={
                "messages": [build_audio_user_message(pcm16, metadata)],
                "call_sid": metadata.get("call_sid"),
                "caller": metadata.get("caller"),
            },
            metadata={
                "call_sid": metadata.get("call_sid", ""),
                "caller": metadata.get("caller", ""),
            },
            stream_mode="messages-tuple",
            multitask_strategy="enqueue",
        ):
            if text := extract_assistant_text_delta(part):
                yield text

    async def aclose(self) -> None:
        await self.client.aclose()


def extract_assistant_text_delta(part: StreamPart) -> str:
    if not part.event.startswith("messages"):
        return ""

    message = _stream_message(part.data)
    if not _is_assistant_message(message):
        return ""
    return _content_text(message.get("content"))


def _stream_message(data: Any) -> dict[str, Any]:
    if isinstance(data, (list, tuple)) and data:
        data = data[0]
    if isinstance(data, dict):
        candidate = data.get("message") or data.get("chunk") or data
        if isinstance(candidate, dict):
            return candidate
    return {}


def _is_assistant_message(message: Mapping[str, Any]) -> bool:
    role = message.get("role")
    if role == "assistant":
        return True

    message_type = str(message.get("type", "")).lower()
    return message_type in {"ai", "aimessage", "aimessagechunk"}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {
                "text",
                "text_delta",
            }:
                parts.append(str(block.get("text", "")))
        return "".join(parts)

    return ""


__all__ = [
    "LangGraphAudioAgent",
    "LangGraphClient",
    "VOICE_AUDIO_INSTRUCTION",
    "build_audio_user_message",
    "extract_assistant_text_delta",
]

"""LangGraph client wrapper for the guard query assistant."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from langgraph_sdk import get_client
from langgraph_sdk.client import LangGraphClient
from langgraph_sdk.schema import StreamPart

from agent.config import Settings


def build_query_user_message(body: Mapping[str, Any]) -> dict[str, str]:
    lines = [
        "请根据以下企业微信门卫查询消息回答：",
        f"会话类型：{body.get('chattype', '') or 'unknown'}",
    ]
    if chat_id := body.get("chatid"):
        lines.append(f"会话ID：{chat_id}")
    if sender := body.get("from", {}).get("userid"):
        lines.append(f"发送人：{sender}")
    if content := body.get("text", {}).get("content"):
        lines.append(f"用户问题：{content}")
    return {"role": "user", "content": "\n".join(lines)}


def resolve_thread_key(body: Mapping[str, Any]) -> str:
    chat_type = str(body.get("chattype", "") or "single")
    sender = str(body.get("from", {}).get("userid", "") or "unknown")
    if chat_type == "group":
        return f"group:{body.get('chatid', '')}:{sender}"
    return f"single:{sender}"


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


@dataclass
class GuardQueryAssistantClient:
    settings: Settings
    client: LangGraphClient = field(init=False)
    _thread_ids: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.client = get_client(
            url=self.settings.langgraph_api_url,
            api_key=self.settings.langgraph_api_key or None,
        )

    async def get_or_create_thread(self, thread_key: str) -> str:
        if thread_key in self._thread_ids:
            return self._thread_ids[thread_key]
        thread = await self.client.threads.create(
            metadata={"channel": "wecom_guard_query"},
            graph_id=self.settings.wecom_query_assistant_id,
        )
        thread_id = str(thread["thread_id"])
        self._thread_ids[thread_key] = thread_id
        return thread_id

    async def stream_reply(
        self,
        thread_key: str,
        body: Mapping[str, Any],
    ) -> AsyncIterator[str]:
        thread_id = await self.get_or_create_thread(thread_key)
        async for part in self.client.runs.stream(
            thread_id=thread_id,
            assistant_id=self.settings.wecom_query_assistant_id,
            input={"messages": [build_query_user_message(body)]},
            metadata={
                "channel": "wecom_guard_query",
                "chatid": str(body.get("chatid", "") or ""),
                "userid": str(body.get("from", {}).get("userid", "") or ""),
            },
            stream_mode="messages-tuple",
            multitask_strategy="enqueue",
            on_disconnect="cancel",
        ):
            if text := extract_assistant_text_delta(part):
                yield text

    async def aclose(self) -> None:
        await self.client.aclose()

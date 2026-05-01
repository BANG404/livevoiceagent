"""LangGraph client wrapper for the guard query assistant."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from langgraph_sdk import get_client
from langgraph_sdk.client import LangGraphClient
from langgraph_sdk.schema import StreamPart

from agent.config import Settings


@dataclass(frozen=True)
class GuardQueryEvent:
    kind: str
    text: str = ""
    tool_name: str = ""
    tool_input: str = ""
    tool_output: str = ""


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


def _is_tool_message(message: Mapping[str, Any]) -> bool:
    role = message.get("role")
    if role == "tool":
        return True
    message_type = str(message.get("type", "")).lower()
    return message_type in {"tool", "toolmessage"}


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


def _extract_tool_calls_from_part(part: StreamPart) -> list[GuardQueryEvent]:
    if not part.event.startswith("updates"):
        return []

    events: list[GuardQueryEvent] = []
    for message in _collect_messages(part.data):
        if _is_assistant_message(message):
            for tool_call in message.get("tool_calls", []) or []:
                function = tool_call.get("function", {})
                name = (
                    function.get("name")
                    or tool_call.get("name")
                    or tool_call.get("tool_name")
                    or ""
                )
                arguments = (
                    function.get("arguments")
                    or tool_call.get("args")
                    or tool_call.get("input")
                    or ""
                )
                call_id = str(tool_call.get("id", "") or "")
                if name:
                    events.append(
                        GuardQueryEvent(
                            kind="tool_start",
                            text=call_id,
                            tool_name=str(name),
                            tool_input=_stringify(arguments),
                        )
                    )
        elif _is_tool_message(message):
            tool_name = str(message.get("name", "") or "")
            tool_call_id = str(message.get("tool_call_id", "") or "")
            tool_output = _content_text(message.get("content")) or _stringify(
                message.get("content")
            )
            if tool_name or tool_call_id:
                events.append(
                    GuardQueryEvent(
                        kind="tool_end",
                        text=tool_call_id,
                        tool_name=tool_name,
                        tool_output=tool_output,
                    )
                )
    return events


def _collect_messages(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            if any(
                key in value for key in ("role", "type", "tool_calls", "tool_call_id")
            ):
                found.append(value)
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)
        elif isinstance(value, tuple):
            for child in value:
                _walk(child)

    _walk(data)
    return found


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


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

    async def stream_reply_events(
        self,
        thread_key: str,
        body: Mapping[str, Any],
    ) -> AsyncIterator[GuardQueryEvent]:
        thread_id = await self.get_or_create_thread(thread_key)
        seen_tool_starts: set[str] = set()
        seen_tool_ends: set[str] = set()

        async for part in self.client.runs.stream(
            thread_id=thread_id,
            assistant_id=self.settings.wecom_query_assistant_id,
            input={"messages": [build_query_user_message(body)]},
            metadata={
                "channel": "wecom_guard_query",
                "chatid": str(body.get("chatid", "") or ""),
                "userid": str(body.get("from", {}).get("userid", "") or ""),
            },
            stream_mode=["messages-tuple", "updates"],
            multitask_strategy="enqueue",
            on_disconnect="cancel",
        ):
            if text := extract_assistant_text_delta(part):
                yield GuardQueryEvent(kind="text", text=text)

            for event in _extract_tool_calls_from_part(part):
                event_id = (
                    event.text or f"{event.kind}:{event.tool_name}:{event.tool_input}"
                )
                if event.kind == "tool_start":
                    if event_id in seen_tool_starts:
                        continue
                    seen_tool_starts.add(event_id)
                elif event.kind == "tool_end":
                    if event_id in seen_tool_ends:
                        continue
                    seen_tool_ends.add(event_id)
                yield event

    async def aclose(self) -> None:
        await self.client.aclose()

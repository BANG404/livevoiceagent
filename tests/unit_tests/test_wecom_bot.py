from types import SimpleNamespace

import pytest
from langgraph_sdk.schema import StreamPart
from wecom_aibot_sdk.types import WsFrame, WsFrameHeaders

from wecom_bot.assistant import (
    build_query_user_message,
    extract_assistant_text_delta,
    resolve_thread_key,
)
from wecom_bot.bridge import WeComGuardQueryBot


def test_build_query_user_message_embeds_wecom_context() -> None:
    message = build_query_user_message(
        {
            "chattype": "group",
            "chatid": "chat-1",
            "from": {"userid": "zhangsan"},
            "text": {"content": "本周来了几辆车？"},
        }
    )

    assert message["role"] == "user"
    assert "chat-1" in message["content"]
    assert "zhangsan" in message["content"]
    assert "本周来了几辆车？" in message["content"]


def test_resolve_thread_key_uses_group_or_single_scope() -> None:
    assert (
        resolve_thread_key(
            {"chattype": "group", "chatid": "chat-1", "from": {"userid": "u1"}}
        )
        == "group:chat-1:u1"
    )
    assert resolve_thread_key({"from": {"userid": "u1"}}) == "single:u1"


def test_extract_assistant_text_delta_from_stream_part() -> None:
    part = StreamPart(
        event="messages",
        data=(
            {
                "type": "AIMessageChunk",
                "content": [{"type": "text_delta", "text": "查询结果"}],
            },
            {"langgraph_node": "guard_query"},
        ),
    )

    assert extract_assistant_text_delta(part) == "查询结果"


@pytest.mark.anyio
async def test_wecom_bot_rejects_unsupported_message_type() -> None:
    bot = WeComGuardQueryBot(
        SimpleNamespace(
            wecom_bot_id="bot-123",
            wecom_bot_secret="secret-xyz",
            wecom_ws_url="wss://example.invalid",
            wecom_heartbeat_seconds=30,
            wecom_log_level="INFO",
            wecom_welcome_message="你好",
            langgraph_api_url="http://127.0.0.1:2024",
            langgraph_api_key="",
            wecom_query_assistant_id="guard_query",
        )
    )

    replies: list[tuple[WsFrame, dict[str, object]]] = []

    async def fake_reply(frame: WsFrame, body: dict[str, object]) -> None:
        replies.append((frame, body))

    bot.client.reply = fake_reply  # type: ignore[method-assign]
    frame = WsFrame(
        headers=WsFrameHeaders(req_id="req-1"),
        body={"msgtype": "image"},
    )

    await bot._on_unsupported_message(frame)

    assert replies
    assert replies[0][1]["msgtype"] == "text"


@pytest.mark.anyio
async def test_wecom_bot_sends_welcome_reply() -> None:
    bot = WeComGuardQueryBot(
        SimpleNamespace(
            wecom_bot_id="bot-123",
            wecom_bot_secret="secret-xyz",
            wecom_ws_url="wss://example.invalid",
            wecom_heartbeat_seconds=30,
            wecom_log_level="INFO",
            wecom_welcome_message="欢迎使用",
            langgraph_api_url="http://127.0.0.1:2024",
            langgraph_api_key="",
            wecom_query_assistant_id="guard_query",
        )
    )

    welcomes: list[dict[str, object]] = []

    async def fake_reply_welcome(frame: WsFrame, body: dict[str, object]) -> None:
        welcomes.append(body)

    bot.client.reply_welcome = fake_reply_welcome  # type: ignore[method-assign]
    frame = WsFrame(headers=WsFrameHeaders(req_id="req-1"), body={})

    await bot._on_enter_chat(frame)

    assert welcomes == [{"msgtype": "text", "text": {"content": "欢迎使用"}}]

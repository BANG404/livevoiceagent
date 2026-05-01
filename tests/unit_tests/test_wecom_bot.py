from types import SimpleNamespace

import pytest
from langgraph_sdk.schema import StreamPart
from wecom_aibot_sdk.types import WsFrame, WsFrameHeaders

from wecom_bot.assistant import (
    GuardQueryEvent,
    build_query_user_message,
    extract_assistant_text_delta,
    resolve_thread_key,
)
from wecom_bot.bridge import WeComGuardQueryBot, _StreamBlock


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
    assert replies[0][1]["msgtype"] == "markdown"


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

    assert welcomes == [{"msgtype": "markdown", "markdown": {"content": "欢迎使用"}}]


def test_wecom_bot_renders_stream_blocks_in_order() -> None:
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

    markdown = bot._render_blocks(
        [
            _StreamBlock(kind="assistant", content="正在整理答案。"),
            _StreamBlock(kind="tool", content="开始调用 `count_visitor_registrations`"),
        ]
    )

    assert markdown == "正在整理答案。\n\n> 开始调用 `count_visitor_registrations`"


@pytest.mark.anyio
async def test_wecom_bot_consumes_tool_events_into_markdown() -> None:
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

    streams: list[str] = []

    async def fake_reply_stream(
        frame: WsFrame, stream_id: str, content: str, finish: bool = False
    ) -> None:
        streams.append(content)

    bot.client.reply_stream = fake_reply_stream  # type: ignore[method-assign]

    async def event_stream():
        yield GuardQueryEvent(
            kind="tool_start",
            text="call-1",
            tool_name="count_visitor_registrations",
            tool_input='{"start_time":"2026-05-01"}',
        )
        yield GuardQueryEvent(
            kind="tool_end",
            text="call-1",
            tool_name="count_visitor_registrations",
            tool_output='{"total": 4}',
        )
        yield GuardQueryEvent(kind="text", text="本周一共 4 辆。")

    blocks = await bot._consume_reply_events(
        WsFrame(headers=WsFrameHeaders(req_id="req-1"), body={}),
        "stream-1",
        [],
        event_stream(),
    )

    assert bot._render_blocks(blocks).endswith("本周一共 4 辆。")
    assert "本周一共 4 辆。" in streams[-1]
    assert "count_visitor_registrations" in streams[-1]
    assert streams[-1].index("开始调用 `count_visitor_registrations`") < streams[
        -1
    ].index("`count_visitor_registrations` 已返回结果")
    assert streams[-1].index("`count_visitor_registrations` 已返回结果") < streams[
        -1
    ].index("本周一共 4 辆。")

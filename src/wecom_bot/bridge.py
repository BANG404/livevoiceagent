"""Enterprise WeChat bot bridge built on top of the WeCom AI bot SDK."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from wecom_aibot_sdk import WSClient
from wecom_aibot_sdk.logger import DefaultLogger
from wecom_aibot_sdk.types import WSClientOptions, WsFrame

from agent.config import Settings
from wecom_bot.assistant import GuardQueryAssistantClient, resolve_thread_key


logger = logging.getLogger(__name__)


def _sdk_log_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


class WeComGuardQueryBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.assistant = GuardQueryAssistantClient(settings)
        self.client = WSClient(
            WSClientOptions(
                bot_id=settings.wecom_bot_id,
                secret=settings.wecom_bot_secret,
                ws_url=settings.wecom_ws_url,
                heartbeat_interval=settings.wecom_heartbeat_seconds * 1000,
                logger=DefaultLogger(level=_sdk_log_level(settings.wecom_log_level)),
            )
        )
        self._bind_handlers()

    def _bind_handlers(self) -> None:
        self.client.on("authenticated", self._on_authenticated)
        self.client.on("event.enter_chat", self._on_enter_chat)
        self.client.on("message.text", self._on_text_message)
        self.client.on("message", self._on_unsupported_message)

    async def _on_authenticated(self, frame: WsFrame) -> None:
        logger.info("WeCom bot authenticated successfully.")

    async def _on_enter_chat(self, frame: WsFrame) -> None:
        welcome = (
            self.settings.wecom_welcome_message
            or "你好，我是门卫查询助手，直接问我访客登记数据就行。"
        )
        await self.client.reply_welcome(
            frame,
            {
                "msgtype": "text",
                "text": {"content": welcome},
            },
        )

    async def _on_text_message(self, frame: WsFrame) -> None:
        body = frame.body or {}
        stream_id = f"stream_{uuid.uuid4().hex}"
        await self.client.reply_stream(
            frame,
            stream_id,
            "正在查询，请稍等...",
            finish=False,
        )

        try:
            thread_key = resolve_thread_key(body)
            final_content = await self._consume_reply_stream(
                frame,
                stream_id,
                self.assistant.stream_reply(thread_key, body),
            )
        except Exception:
            logger.exception("WeCom text message handling failed.")
            final_content = "查询失败，请稍后再试。"

        await self.client.reply_stream(
            frame,
            stream_id,
            final_content,
            finish=True,
        )

    async def _on_unsupported_message(self, frame: WsFrame) -> None:
        body = frame.body or {}
        if body.get("msgtype") == "text":
            return
        await self.client.reply(
            frame,
            {
                "msgtype": "text",
                "text": {"content": "目前只支持文本查询，请直接发送文字问题。"},
            },
        )

    async def _consume_reply_stream(
        self,
        frame: WsFrame,
        stream_id: str,
        deltas: AsyncIterator[str],
    ) -> str:
        accumulated = ""
        async for delta in deltas:
            accumulated += delta
            await self.client.reply_stream(
                frame,
                stream_id,
                accumulated,
                finish=False,
            )
        return accumulated or "暂时没查到结果。"

    async def run_forever(self) -> None:
        await self.client.connect_async()
        while self.client.is_connected:
            await asyncio.sleep(1)

    async def aclose(self) -> None:
        try:
            await self.client.disconnect()
        finally:
            await self.assistant.aclose()

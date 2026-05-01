"""Enterprise WeChat bot bridge built on top of the WeCom AI bot SDK."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from wecom_aibot_sdk import WSClient
from wecom_aibot_sdk.logger import DefaultLogger
from wecom_aibot_sdk.types import WSClientOptions, WsFrame

from agent.config import Settings
from wecom_bot.assistant import (
    GuardQueryAssistantClient,
    GuardQueryEvent,
    resolve_thread_key,
)


logger = logging.getLogger(__name__)


@dataclass
class _StreamBlock:
    kind: str
    content: str


def _sdk_log_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


def _truncate_text(text: str, limit: int = 120) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


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
        await self.client.reply_welcome(frame, self._markdown_body(welcome))

    async def _on_text_message(self, frame: WsFrame) -> None:
        body = frame.body or {}
        stream_id = f"stream_{uuid.uuid4().hex}"
        blocks = [_StreamBlock(kind="assistant", content="正在思考，请稍等...")]
        await self.client.reply_stream(
            frame,
            stream_id,
            self._render_blocks(blocks),
            finish=False,
        )

        try:
            thread_key = resolve_thread_key(body)
            blocks = await self._consume_reply_events(
                frame,
                stream_id,
                blocks,
                self.assistant.stream_reply_events(thread_key, body),
            )
        except Exception:
            logger.exception("WeCom text message handling failed.")
            blocks = [_StreamBlock(kind="assistant", content="查询失败，请稍后再试。")]

        await self.client.reply_stream(
            frame,
            stream_id,
            self._render_blocks(blocks),
            finish=True,
        )

    async def _on_unsupported_message(self, frame: WsFrame) -> None:
        body = frame.body or {}
        if body.get("msgtype") == "text":
            return
        await self.client.reply(
            frame, self._markdown_body("目前只支持文本查询，请直接发送文字问题。")
        )

    async def _consume_reply_events(
        self,
        frame: WsFrame,
        stream_id: str,
        blocks: list[_StreamBlock],
        events: AsyncIterator[GuardQueryEvent],
    ) -> list[_StreamBlock]:
        async for event in events:
            if event.kind == "text":
                self._append_text_block(blocks, event.text)
                await self.client.reply_stream(
                    frame,
                    stream_id,
                    self._render_blocks(blocks),
                    finish=False,
                )
                continue

            if event.kind == "tool_start":
                detail = f"开始调用 `{event.tool_name}`"
                if event.tool_input:
                    detail += f"，输入：`{_truncate_text(event.tool_input, 70)}`"
                blocks.append(_StreamBlock(kind="tool", content=detail))
                await self.client.reply_stream(
                    frame,
                    stream_id,
                    self._render_blocks(blocks),
                    finish=False,
                )
                continue

            if event.kind == "tool_end":
                detail = f"`{event.tool_name or '工具'}` 已返回结果"
                if event.tool_output:
                    detail += f"：`{_truncate_text(event.tool_output, 70)}`"
                blocks.append(_StreamBlock(kind="tool", content=detail))
                await self.client.reply_stream(
                    frame,
                    stream_id,
                    self._render_blocks(blocks),
                    finish=False,
                )
        if not any(
            block.kind == "assistant" and block.content.strip() for block in blocks
        ):
            return [_StreamBlock(kind="assistant", content="暂时没查到结果。")]
        return blocks

    def _markdown_body(self, content: str) -> dict[str, object]:
        return {"msgtype": "markdown", "markdown": {"content": content}}

    def _append_text_block(self, blocks: list[_StreamBlock], text: str) -> None:
        if blocks and blocks[-1].kind == "assistant":
            if blocks[-1].content == "正在思考，请稍等...":
                blocks[-1].content = text
            else:
                blocks[-1].content += text
            return
        blocks.append(_StreamBlock(kind="assistant", content=text))

    def _render_blocks(self, blocks: list[_StreamBlock]) -> str:
        rendered: list[str] = []
        for block in blocks:
            content = block.content.strip()
            if not content:
                continue
            if block.kind == "tool":
                rendered.append(f"> {content}")
            else:
                rendered.append(content)
        return "\n\n".join(rendered) or "正在思考，请稍等..."

    async def run_forever(self) -> None:
        await self.client.connect_async()
        while self.client.is_connected:
            await asyncio.sleep(1)

    async def aclose(self) -> None:
        try:
            await self.client.disconnect()
        finally:
            await self.assistant.aclose()

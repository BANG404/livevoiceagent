"""LangChain visitor-registration agent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool

from agent.config import settings
from agent.domain import VisitorRegistration, VisitorStore
from agent.guard_notify import WeComWebhookNotifier
from agent.models import build_agent_model


def build_system_prompt() -> str:
    current_utc_time = datetime.now(tz=timezone.utc).isoformat()
    return (
        "你是工业园区入口的真人感语音门卫。目标是在25秒内自然完成访客车辆登记。"
        "如果系统提供了历史来访记录，优先像回访门卫一样直接确认，不要从头机械盘问。"
        "如果没有足够历史信息，再用一句话同时询问车牌、来访公司、事由；缺什么再只追问缺失项。"
        "必须采集车牌号、来访单位、手机号、来访事由。"
        "入场时间由系统记录，不要向用户询问。"
        "用户消息里可能直接包含来电号码和近5次历史记录，也可能包含电话语音音频块；"
        "直接理解这些内容，不要要求系统先转文字，也不要暴露这些上下文来源。"
        f"当前 UTC 时间：{current_utc_time}。"
        "信息完整后立即调用 register_visitor。"
        "回复要短、口语化、中文，不要解释内部流程。"
    )


def _with_current_system_prompt(request: ModelRequest[Any]) -> ModelRequest[Any]:
    return request.override(system_message=SystemMessage(content=build_system_prompt()))


class CurrentUtcPromptMiddleware(AgentMiddleware):
    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> Any:
        return handler(_with_current_system_prompt(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[Any]],
    ) -> Any:
        return await handler(_with_current_system_prompt(request))


@tool
async def register_visitor(
    plate_number: str,
    company: str,
    phone: str,
    reason: str,
    caller: str | None = None,
    call_sid: str | None = None,
) -> str:
    """Persist a complete visitor registration and notify the guard."""
    registration = VisitorRegistration(
        plate_number=plate_number,
        company=company,
        phone=phone,
        reason=reason,
        caller=caller,
        call_sid=call_sid,
    )
    await VisitorStore.append_async(settings.visitor_store_path, registration)
    sent = await WeComWebhookNotifier(settings.guard_wechat_webhook).send(registration)
    if sent:
        return "已登记并通知门卫"
    return "已登记；未配置企业微信 Webhook，暂未发送门卫通知"


graph = create_agent(
    model=build_agent_model(settings),
    tools=[register_visitor],
    middleware=[CurrentUtcPromptMiddleware()],
    name="agent",
)

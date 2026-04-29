"""LangChain visitor-registration agent graph."""

from __future__ import annotations

import ast
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


def build_system_prompt() -> str:
    current_utc_time = datetime.now(tz=timezone.utc).isoformat()
    return (
        "你是工业园区入口的真人感语音门卫。目标是在25秒内自然完成访客车辆登记。"
        "先用一句话同时询问车牌、来访公司、事由；缺什么再只追问缺失项。"
        "必须采集车牌号、来访单位、手机号、来访事由。"
        "入场时间由系统记录，不要向用户询问。"
        f"当前 UTC 时间：{current_utc_time}。"
        "信息完整后立即调用 register_visitor；如果用户提供手机号或车牌号且像回访，"
        "可调用 lookup_recent_visit 辅助确认。"
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
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression safely.

    Supported operators: +, -, *, /, %, ** and parentheses.
    """
    parsed = ast.parse(expression, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )

    for node in ast.walk(parsed):
        if not isinstance(node, allowed_nodes):
            raise ValueError("Expression contains unsupported syntax")

    result: Any = eval(compile(parsed, "<calculator>", "eval"), {"__builtins__": {}}, {})
    return str(result)


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
    VisitorStore(settings.visitor_store_path).append(registration)
    sent = await WeComWebhookNotifier(settings.guard_wechat_webhook).send(registration)
    if sent:
        return "已登记并通知门卫"
    return "已登记；未配置企业微信 Webhook，暂未发送门卫通知"


@tool
def lookup_recent_visit(phone: str | None = None, plate_number: str | None = None) -> str:
    """Look up the most recent visit by phone or plate_number for repeat visitors."""
    phone = phone.strip() if phone else None
    plate_number = plate_number.strip() if plate_number else None
    if not phone and not plate_number:
        return "请提供手机号或车牌号"

    latest = VisitorStore(settings.visitor_store_path).latest_by_phone_or_plate(
        phone=phone,
        plate_number=plate_number,
    )
    if latest is None:
        return "未找到历史来访记录"
    return latest.model_dump_json()


graph = create_agent(
    model=settings.agent_model,
    tools=[calculator, register_visitor, lookup_recent_visit],
    middleware=[CurrentUtcPromptMiddleware()],
    name="agent",
)

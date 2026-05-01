"""LangGraph assistant for guard-side visitor data queries."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool

from agent.config import settings
from agent.domain import VisitorStore
from agent.models import build_agent_model


def build_query_system_prompt() -> str:
    return (
        "你是园区门卫的查询助手，负责回答访客车辆登记数据相关问题。"
        "默认使用北京时间理解“今天、本周、本月、昨天”等时间词，并在需要时先调用工具。"
        "只基于系统登记数据回答，不要编造不存在的访客信息。"
        "如果问题涉及姓名，但当前数据没有直接存储姓名字段，先尝试用关键词检索；"
        "仍然无法确认时，要明确说明当前登记表主要按车牌、单位、手机号、事由检索。"
        "回答简洁、直接、中文。"
    )


def _with_query_system_prompt(request: ModelRequest[Any]) -> ModelRequest[Any]:
    return request.override(
        system_message=SystemMessage(content=build_query_system_prompt())
    )


class GuardQueryPromptMiddleware(AgentMiddleware):
    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> Any:
        return handler(_with_query_system_prompt(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[Any]],
    ) -> Any:
        return await handler(_with_query_system_prompt(request))


def _parse_datetime(
    value: str | None,
    *,
    end_of_day: bool = False,
) -> datetime | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) == 10:
        parsed_date = datetime.strptime(cleaned, "%Y-%m-%d").date()
        parsed_time = time.max.replace(microsecond=0) if end_of_day else time.min
        return datetime.combine(parsed_date, parsed_time)
    return datetime.fromisoformat(cleaned)


def _store() -> VisitorStore:
    return VisitorStore(settings.visitor_store_path)


@tool
async def count_visitor_registrations(
    start_time: str | None = None,
    end_time: str | None = None,
    company: str | None = None,
    phone: str | None = None,
    plate_number: str | None = None,
    reason_keyword: str | None = None,
    caller: str | None = None,
    keyword: str | None = None,
) -> str:
    """Count visitor registrations with optional time and field filters.

    Dates can be `YYYY-MM-DD` or full ISO datetimes.
    """
    total = _store().count_visits(
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time, end_of_day=True),
        company=company,
        phone=phone,
        plate_number=plate_number,
        reason_keyword=reason_keyword,
        caller=caller,
        keyword=keyword,
    )
    return json.dumps(
        {
            "total": total,
            "filters": {
                "start_time": start_time,
                "end_time": end_time,
                "company": company,
                "phone": phone,
                "plate_number": plate_number,
                "reason_keyword": reason_keyword,
                "caller": caller,
                "keyword": keyword,
            },
        },
        ensure_ascii=False,
    )


@tool
async def search_visitor_registrations(
    start_time: str | None = None,
    end_time: str | None = None,
    company: str | None = None,
    phone: str | None = None,
    plate_number: str | None = None,
    reason_keyword: str | None = None,
    caller: str | None = None,
    keyword: str | None = None,
    limit: int = 10,
) -> str:
    """Search visitor registrations and return the latest matching rows."""
    visits = _store().query_visits(
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time, end_of_day=True),
        company=company,
        phone=phone,
        plate_number=plate_number,
        reason_keyword=reason_keyword,
        caller=caller,
        keyword=keyword,
        limit=max(1, min(limit, 20)),
    )
    return json.dumps(
        [
            {
                "plate_number": visit.plate_number,
                "company": visit.company,
                "phone": visit.phone,
                "reason": visit.reason,
                "entry_time": visit.entry_time.isoformat(),
                "caller": visit.caller,
                "call_sid": visit.call_sid,
            }
            for visit in visits
        ],
        ensure_ascii=False,
    )


@tool
async def find_busiest_visit_hour(
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    """Find the busiest entry hour in the selected time range."""
    busiest = _store().busiest_hour(
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time, end_of_day=True),
    )
    return json.dumps(busiest or {}, ensure_ascii=False)


@tool
async def list_repeat_visitors(
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 5,
) -> str:
    """List the most frequent visitors in the selected time range."""
    visitors = _store().top_repeat_visitors(
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time, end_of_day=True),
        limit=max(1, min(limit, 10)),
    )
    return json.dumps(visitors, ensure_ascii=False)


graph = create_agent(
    model=build_agent_model(settings),
    tools=[
        count_visitor_registrations,
        search_visitor_registrations,
        find_busiest_visit_hour,
        list_repeat_visitors,
    ],
    middleware=[GuardQueryPromptMiddleware()],
    name="guard_query",
)

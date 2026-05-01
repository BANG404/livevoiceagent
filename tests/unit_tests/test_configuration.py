from types import SimpleNamespace

import pytest
import agent.graph as graph_module
from langgraph.pregel import Pregel

from agent.domain import VisitorRegistration, VisitorStore
from agent.graph import (
    build_system_prompt,
    graph,
    register_visitor,
)
from voice.audio import UtteranceBuffer, mulaw_payload_to_pcm16, pcm16_to_mulaw_payload


def test_graph_compiles() -> None:
    assert isinstance(graph, Pregel)


def test_system_prompt_includes_current_utc_time() -> None:
    prompt = build_system_prompt()
    assert "当前 UTC 时间：" in prompt
    assert "T" in prompt
    assert "历史来访记录" in prompt


def test_visitor_guard_message() -> None:
    registration = VisitorRegistration(
        plate_number="沪A12345",
        company="蓝色鲸鱼科技",
        phone="13800001234",
        reason="送货",
    )
    message = registration.guard_message()
    assert "沪A12345" in message
    assert "蓝色鲸鱼科技" in message
    assert "13800001234" in message


def test_visitor_store_latest_by_phone_or_plate(tmp_path) -> None:
    store = VisitorStore(str(tmp_path / "visitors.sqlite3"))
    store.append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="送货",
        )
    )
    store.append(
        VisitorRegistration(
            plate_number="苏B67890",
            company="绿色海豚贸易",
            phone="13900005678",
            reason="拜访",
        )
    )

    assert store.latest_by_phone("13800001234").company == "蓝色鲸鱼科技"
    assert store.latest_by_phone("+86 13900005678").company == "绿色海豚贸易"
    assert store.latest_by_plate_number("苏b67890").phone == "13900005678"


def test_visitor_store_recent_by_phone_returns_latest_five(tmp_path) -> None:
    store = VisitorStore(str(tmp_path / "visitors.sqlite3"))
    for index in range(6):
        store.append(
            VisitorRegistration(
                plate_number=f"沪A1234{index}",
                company="蓝色鲸鱼科技",
                phone="13800001234",
                reason=f"送货{index}",
            )
        )

    recent = store.recent_by_phone("+86 13800001234", limit=5)

    assert len(recent) == 5
    assert recent[0].reason == "送货5"
    assert recent[-1].reason == "送货1"


@pytest.mark.anyio
async def test_register_visitor_persists_plate_number(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    monkeypatch.setattr(
        graph_module,
        "settings",
        SimpleNamespace(visitor_store_path=str(store_path), guard_wechat_webhook=""),
    )

    result = await register_visitor.ainvoke(
        {
            "plate_number": "沪A12345",
            "company": "蓝色鲸鱼科技",
            "phone": "13800001234",
            "reason": "送货",
        }
    )

    latest = VisitorStore(str(store_path)).latest_by_plate_number("沪A12345")
    assert result == "已登记；未配置企业微信 Webhook，暂未发送门卫通知"
    assert latest is not None
    assert latest.phone == "13800001234"


def test_register_visitor_storage_is_queryable_by_caller_id(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    monkeypatch.setattr(
        graph_module,
        "settings",
        SimpleNamespace(visitor_store_path=str(store_path), guard_wechat_webhook=""),
    )
    VisitorStore(str(store_path)).append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="送货",
        )
    )

    latest = VisitorStore(str(store_path)).latest_by_phone("+86 13800001234")
    assert latest is not None
    assert latest.plate_number == "沪A12345"


def test_twilio_mulaw_round_trip() -> None:
    pcm16 = b"\x00\x00" * 160
    payload = pcm16_to_mulaw_payload(pcm16)
    decoded = mulaw_payload_to_pcm16(payload)
    assert len(decoded) == len(pcm16)
    assert set(decoded) <= {0}


def test_utterance_buffer_closes_after_silence() -> None:
    buffer = UtteranceBuffer(silence_frames_to_close=2, min_speech_frames=1)
    assert buffer.push(b"\xff\x7f" * 160) is None
    assert buffer.push(b"\x00\x00" * 160) is None
    utterance = buffer.push(b"\x00\x00" * 160)
    assert utterance is not None

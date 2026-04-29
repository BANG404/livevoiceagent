from types import SimpleNamespace

import pytest
import agent.graph as graph_module
from langgraph.pregel import Pregel

from agent.domain import VisitorRegistration, VisitorStore
from agent.graph import (
    build_system_prompt,
    calculator,
    graph,
    lookup_recent_visit,
    register_visitor,
)
from voice.audio import UtteranceBuffer, mulaw_payload_to_pcm16, pcm16_to_mulaw_payload


def test_graph_compiles() -> None:
    assert isinstance(graph, Pregel)


def test_calculator_tool() -> None:
    result = calculator.invoke({"expression": "2 + 3 * 4"})
    assert result == "14"


def test_system_prompt_includes_current_utc_time() -> None:
    prompt = build_system_prompt()
    assert "当前 UTC 时间：" in prompt
    assert "T" in prompt


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
    store = VisitorStore(str(tmp_path / "visitors.jsonl"))
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
    assert store.latest_by_plate_number("苏b67890").phone == "13900005678"


def test_lookup_recent_visit_supports_plate_number(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.jsonl"
    VisitorStore(str(store_path)).append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="送货",
        )
    )
    monkeypatch.setattr(
        graph_module,
        "settings",
        SimpleNamespace(visitor_store_path=str(store_path)),
    )

    result = lookup_recent_visit.invoke({"plate_number": "沪A12345"})

    assert "沪A12345" in result
    assert "蓝色鲸鱼科技" in result


@pytest.mark.anyio
async def test_register_visitor_persists_plate_number(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.jsonl"
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

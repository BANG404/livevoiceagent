from types import SimpleNamespace

import pytest
import agent.graph as graph_module
from langgraph.pregel import Pregel

from agent.domain import VisitorRegistration, VisitorStore
from agent.graph import (
    build_system_prompt,
    graph,
    guard_notify,
)
from agent.query_graph import (
    count_visitor_registrations,
    find_busiest_visit_hour,
    graph as guard_query_graph,
    list_repeat_visitors,
    search_visitor_registrations,
)
from voice.audio import UtteranceBuffer, mulaw_payload_to_pcm16, pcm16_to_mulaw_payload


def test_graph_compiles() -> None:
    assert isinstance(graph, Pregel)
    assert isinstance(guard_query_graph, Pregel)


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


def test_visitor_store_query_and_analytics(tmp_path) -> None:
    store = VisitorStore(str(tmp_path / "visitors.sqlite3"))
    store.append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="张师傅送货",
        )
    )
    store.append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="张师傅送货",
        )
    )
    store.append(
        VisitorRegistration(
            plate_number="苏B67890",
            company="绿色海豚贸易",
            phone="13900005678",
            reason="面试",
        )
    )

    assert store.count_visits(keyword="张师傅") == 2
    assert len(store.query_visits(company="蓝色鲸鱼", limit=5)) == 2
    assert store.busiest_hour() is not None
    repeat_visitors = store.top_repeat_visitors(limit=2)
    assert repeat_visitors[0]["plate_number"] == "沪A12345"
    assert repeat_visitors[0]["total_visits"] == 2


@pytest.mark.anyio
async def test_guard_notify_persists_plate_number(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    monkeypatch.setattr(
        graph_module,
        "settings",
        SimpleNamespace(visitor_store_path=str(store_path), guard_wechat_webhook=""),
    )

    result = await guard_notify.ainvoke(
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


@pytest.mark.anyio
async def test_guard_notify_reads_caller_and_call_sid_from_metadata(
    tmp_path, monkeypatch
) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    monkeypatch.setattr(
        graph_module,
        "settings",
        SimpleNamespace(visitor_store_path=str(store_path), guard_wechat_webhook=""),
    )

    await guard_notify.ainvoke(
        {
            "plate_number": "沪B54321",
            "company": "深蓝物流",
            "phone": "13900001234",
            "reason": "提货",
        },
        config={
            "metadata": {
                "caller": "+8613900001234",
                "call_sid": "CA123",
            }
        },
    )

    latest = VisitorStore(str(store_path)).latest_by_plate_number("沪B54321")
    assert latest is not None
    assert latest.caller == "+8613900001234"
    assert latest.call_sid == "CA123"


@pytest.mark.anyio
async def test_visitor_store_async_recent_by_phone_returns_latest_five(
    tmp_path,
) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    store = VisitorStore(str(store_path))
    for index in range(6):
        store.append(
            VisitorRegistration(
                plate_number=f"沪A2234{index}",
                company="蓝色鲸鱼科技",
                phone="13800001234",
                reason=f"回访{index}",
            )
        )

    recent = await VisitorStore.recent_by_phone_async(
        str(store_path),
        "+86 13800001234",
        limit=5,
    )

    assert len(recent) == 5
    assert recent[0].reason == "回访5"
    assert recent[-1].reason == "回访1"


@pytest.mark.anyio
async def test_guard_query_tools_use_visitor_store(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "visitors.sqlite3"
    store = VisitorStore(str(store_path))
    store.append(
        VisitorRegistration(
            plate_number="沪A12345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="张师傅送货",
        )
    )
    store.append(
        VisitorRegistration(
            plate_number="沪A22345",
            company="蓝色鲸鱼科技",
            phone="13800001234",
            reason="张师傅送货",
        )
    )
    monkeypatch.setattr(
        "agent.query_graph.settings",
        SimpleNamespace(visitor_store_path=str(store_path)),
    )

    count_payload = await count_visitor_registrations.ainvoke({"keyword": "张师傅"})
    search_payload = await search_visitor_registrations.ainvoke(
        {"company": "蓝色鲸鱼", "limit": 5}
    )
    busiest_payload = await find_busiest_visit_hour.ainvoke({})
    repeat_payload = await list_repeat_visitors.ainvoke({"limit": 3})

    assert '"total": 2' in count_payload
    assert "沪A12345" in search_payload or "沪A22345" in search_payload
    assert "hour_bucket" in busiest_payload
    assert '"total_visits": 2' in repeat_payload


def test_guard_notify_storage_is_queryable_by_caller_id(
    tmp_path, monkeypatch
) -> None:
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


def test_settings_support_dashscope_asr_configuration(monkeypatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "dashscope")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv(
        "DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/api/v1"
    )
    monkeypatch.setenv("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash-us")
    monkeypatch.setenv("DASHSCOPE_ASR_LANGUAGE", "zh")

    from importlib import reload
    import agent.config as config_module

    reload(config_module)

    try:
        reloaded = config_module.Settings()
        assert reloaded.stt_provider == "dashscope"
        assert reloaded.dashscope_api_key == "sk-test"
        assert (
            reloaded.dashscope_base_url == "https://dashscope-intl.aliyuncs.com/api/v1"
        )
        assert reloaded.dashscope_asr_model == "qwen3-asr-flash-us"
        assert reloaded.dashscope_asr_language == "zh"
    finally:
        reload(config_module)


def test_settings_support_wecom_query_bot_configuration(monkeypatch) -> None:
    monkeypatch.setenv("WECOM_QUERY_ASSISTANT_ID", "guard_query")
    monkeypatch.setenv("WECOM_BOT_ID", "bot-123")
    monkeypatch.setenv("WECOM_BOT_SECRET", "secret-xyz")
    monkeypatch.setenv("WECOM_HEARTBEAT_SECONDS", "45")

    from importlib import reload
    import agent.config as config_module

    reload(config_module)

    try:
        reloaded = config_module.Settings()
        assert reloaded.wecom_query_assistant_id == "guard_query"
        assert reloaded.wecom_bot_id == "bot-123"
        assert reloaded.wecom_bot_secret == "secret-xyz"
        assert reloaded.wecom_heartbeat_seconds == 45
    finally:
        reload(config_module)

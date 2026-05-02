import asyncio
import json

from fastapi.testclient import TestClient

from agent.domain import VisitorRegistration
import voice.app as voice_app_module
from voice.app import app
from voice.audio import FRAME_BYTES_PCM16, pcm16_to_mulaw_payload


class _ImmediateUtteranceBuffer:
    def __init__(self, *args, **kwargs) -> None:
        self._done = False

    def push(self, pcm16: bytes) -> bytes | None:
        if self._done:
            return None
        self._done = True
        return pcm16

    def consume_speech_started(self) -> bool:
        return False


class _FakeAgent:
    def __init__(self, settings) -> None:
        self.closed = False
        self.cancelled_threads: list[str] = []
        self.uses_stt = False

    async def create_thread(self, metadata: dict[str, str]) -> str:
        assert metadata["call_sid"] == "CA123"
        assert metadata["caller"] == "+8613800001234"
        return "thread-1"

    async def stream_welcome_text(
        self,
        thread_id: str,
        metadata: dict[str, str],
        recent_visits: list[VisitorRegistration],
    ):
        assert thread_id == "thread-1"
        assert metadata["caller"] == "+8613800001234"
        assert len(recent_visits) == 1
        assert recent_visits[0].plate_number == "沪A12345"
        yield "张师傅您好，今天还是来蓝色鲸鱼送货吗？"

    async def stream_reply_from_audio(
        self,
        thread_id: str,
        pcm16: bytes,
        metadata: dict[str, str],
    ):
        assert thread_id == "thread-1"
        assert pcm16
        assert metadata["call_sid"] == "CA123"
        yield "收到，请报车牌号。"

    async def aclose(self) -> None:
        self.closed = True

    async def cancel_active_run(self, thread_id: str) -> None:
        self.cancelled_threads.append(thread_id)


class _FakeTts:
    async def stream_pcm16(self, text: str):
        assert "车牌号" in text or "张师傅您好" in text
        yield b"\x01\x00" * (FRAME_BYTES_PCM16 // 2)


class _BargeInUtteranceBuffer:
    def __init__(self, *args, **kwargs) -> None:
        self.calls = 0
        self._speech_started = False

    def push(self, pcm16: bytes) -> bytes | None:
        self.calls += 1
        if self.calls == 1:
            return pcm16
        if self.calls == 2:
            self._speech_started = True
        return None

    def consume_speech_started(self) -> bool:
        started = self._speech_started
        self._speech_started = False
        return started


class _SlowTts:
    async def stream_pcm16(self, text: str):
        assert "车牌号" in text or "张师傅您好" in text
        for _ in range(4):
            yield b"\x01\x00" * (FRAME_BYTES_PCM16 // 2)
            await asyncio.sleep(0.05)


class _FakeStore:
    def __init__(self, path: str) -> None:
        self.path = path

    @staticmethod
    async def recent_by_phone_async(
        path: str,
        phone: str,
        limit: int = 5,
    ) -> list[VisitorRegistration]:
        assert path
        assert phone == "+8613800001234"
        assert limit == 5
        return [
            VisitorRegistration(
                plate_number="沪A12345",
                company="蓝色鲸鱼科技",
                phone="13800001234",
                reason="送货",
            )
        ]


def test_twilio_media_websocket_accepts_local_client(monkeypatch) -> None:
    monkeypatch.setattr(voice_app_module, "UtteranceBuffer", _ImmediateUtteranceBuffer)
    monkeypatch.setattr(voice_app_module, "LangGraphAudioAgent", _FakeAgent)
    monkeypatch.setattr(voice_app_module, "build_tts", lambda settings: _SlowTts())
    monkeypatch.setattr(voice_app_module, "VisitorStore", _FakeStore)

    client = TestClient(app)
    payload = pcm16_to_mulaw_payload(b"\x02\x00" * (FRAME_BYTES_PCM16 // 2))

    with client.websocket_connect("/twilio/media") as websocket:
        websocket.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ123",
                        "customParameters": {
                            "call_sid": "CA123",
                            "caller": "+8613800001234",
                        },
                    },
                }
            )
        )
        websocket.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": "MZ123",
                    "media": {"payload": payload},
                }
            )
        )

        reply = websocket.receive_json()

        assert reply["event"] == "media"
        assert reply["streamSid"] == "MZ123"
        assert reply["media"]["payload"]

        second_reply = websocket.receive_json()
        assert second_reply["event"] == "media"
        assert second_reply["streamSid"] == "MZ123"

        websocket.send_text(json.dumps({"event": "stop", "streamSid": "MZ123"}))


def test_twilio_media_websocket_sends_clear_on_barge_in(monkeypatch) -> None:
    agent_instances: list[_FakeAgent] = []

    def build_agent(settings) -> _FakeAgent:
        agent = _FakeAgent(settings)
        agent_instances.append(agent)
        return agent

    monkeypatch.setattr(voice_app_module, "UtteranceBuffer", _BargeInUtteranceBuffer)
    monkeypatch.setattr(voice_app_module, "LangGraphAudioAgent", build_agent)
    monkeypatch.setattr(voice_app_module, "build_tts", lambda settings: _SlowTts())
    monkeypatch.setattr(voice_app_module, "VisitorStore", _FakeStore)

    client = TestClient(app)
    payload = pcm16_to_mulaw_payload(b"\x02\x00" * (FRAME_BYTES_PCM16 // 2))

    with client.websocket_connect("/twilio/media") as websocket:
        websocket.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ123",
                        "customParameters": {
                            "call_sid": "CA123",
                            "caller": "+8613800001234",
                        },
                    },
                }
            )
        )
        websocket.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": "MZ123",
                    "media": {"payload": payload},
                }
            )
        )

        first_reply = websocket.receive_json()
        assert first_reply["event"] == "media"

        websocket.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": "MZ123",
                    "media": {"payload": payload},
                }
            )
        )

        next_event = websocket.receive_json()
        if next_event != {"event": "clear", "streamSid": "MZ123"}:
            next_event = websocket.receive_json()
        assert next_event == {"event": "clear", "streamSid": "MZ123"}

    assert len(agent_instances) == 1
    assert agent_instances[0].cancelled_threads == ["thread-1"]

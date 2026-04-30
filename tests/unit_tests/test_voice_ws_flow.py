import json

from fastapi.testclient import TestClient

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


class _FakeAgent:
    def __init__(self, settings) -> None:
        self.closed = False

    async def create_thread(self, metadata: dict[str, str]) -> str:
        assert metadata["call_sid"] == "CA123"
        assert metadata["caller"] == "+8613800001234"
        return "thread-1"

    async def stream_reply_text(self, thread_id: str, pcm16: bytes, metadata: dict[str, str]):
        assert thread_id == "thread-1"
        assert pcm16
        assert metadata["call_sid"] == "CA123"
        yield "收到，请报车牌号。"

    async def aclose(self) -> None:
        self.closed = True


class _FakeTts:
    async def stream_pcm16(self, text: str):
        assert "车牌号" in text
        yield b"\x01\x00" * (FRAME_BYTES_PCM16 // 2)


def test_twilio_media_websocket_accepts_local_client(monkeypatch) -> None:
    monkeypatch.setattr(voice_app_module, "UtteranceBuffer", _ImmediateUtteranceBuffer)
    monkeypatch.setattr(voice_app_module, "LangGraphAudioAgent", _FakeAgent)
    monkeypatch.setattr(voice_app_module, "build_tts", lambda settings: _FakeTts())

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

        websocket.send_text(json.dumps({"event": "stop", "streamSid": "MZ123"}))

"""Runtime configuration for the voice visitor agent."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    agent_model: str = _getenv("AGENT_MODEL", "anthropic:claude-sonnet-4-6")
    public_base_url: str = _getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    guard_wechat_webhook: str = _getenv("GUARD_WECHAT_WEBHOOK")
    visitor_store_path: str = _getenv("VISITOR_STORE_PATH", "data/visitors.jsonl")
    park_name: str = _getenv("PARK_NAME", "园区")
    agent_voice: str = _getenv("AGENT_VOICE", "zf_001")
    openai_api_key: str = _getenv("OPENAI_API_KEY")
    stt_model: str = _getenv("STT_MODEL", "gpt-4o-mini-transcribe")
    tts_provider: str = _getenv("TTS_PROVIDER", "kokoro")
    kokoro_lang_code: str = _getenv("KOKORO_LANG_CODE", "z")

    @property
    def websocket_base_url(self) -> str:
        if self.public_base_url.startswith("https://"):
            return "wss://" + self.public_base_url.removeprefix("https://")
        if self.public_base_url.startswith("http://"):
            return "ws://" + self.public_base_url.removeprefix("http://")
        return self.public_base_url


settings = Settings()

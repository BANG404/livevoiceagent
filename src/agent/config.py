"""Runtime configuration for the voice visitor agent."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(override=False)


def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _getint(name: str, default: int) -> int:
    value = _getenv(name)
    return int(value) if value else default


def _getfloat(name: str, default: float) -> float:
    value = _getenv(name)
    return float(value) if value else default


@dataclass(frozen=True)
class Settings:
    agent_model: str = _getenv("AGENT_MODEL", "google_genai:gemini-2.5-flash")
    google_api_key: str = _getenv("GOOGLE_API_KEY", "your-google-api-key")
    openai_api_key: str = _getenv("OPENAI_API_KEY")
    openai_base_url: str = _getenv("OPENAI_BASE_URL")
    stt_provider: str = _getenv("STT_PROVIDER")
    dashscope_api_key: str = _getenv("DASHSCOPE_API_KEY")
    dashscope_base_url: str = _getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
    )
    dashscope_asr_model: str = _getenv("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash")
    dashscope_asr_language: str = _getenv("DASHSCOPE_ASR_LANGUAGE")
    langgraph_api_url: str = _getenv("LANGGRAPH_API_URL", "http://127.0.0.1:2024")
    langgraph_api_key: str = _getenv("LANGGRAPH_API_KEY")
    langgraph_assistant_id: str = _getenv("LANGGRAPH_ASSISTANT_ID", "agent")
    wecom_query_assistant_id: str = _getenv("WECOM_QUERY_ASSISTANT_ID", "guard_query")
    public_base_url: str = _getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    guard_wechat_webhook: str = _getenv("GUARD_WECHAT_WEBHOOK")
    wecom_bot_id: str = _getenv("WECOM_BOT_ID")
    wecom_bot_secret: str = _getenv("WECOM_BOT_SECRET")
    wecom_ws_url: str = _getenv("WECOM_WS_URL", "wss://openws.work.weixin.qq.com")
    wecom_welcome_message: str = _getenv(
        "WECOM_WELCOME_MESSAGE", "你好，我是门卫查询助手，直接问我访客登记数据就行。"
    )
    wecom_heartbeat_seconds: int = _getint("WECOM_HEARTBEAT_SECONDS", 30)
    wecom_log_level: str = _getenv("WECOM_LOG_LEVEL", "INFO")
    visitor_store_path: str = _getenv("VISITOR_STORE_PATH", "data/visitors.sqlite3")
    park_name: str = _getenv("PARK_NAME", "园区")
    agent_voice: str = _getenv("AGENT_VOICE", "zf_xiaobei")
    tts_provider: str = _getenv("TTS_PROVIDER", "kokoro")
    kokoro_lang_code: str = _getenv("KOKORO_LANG_CODE", "z")
    kokoro_repo_id: str = _getenv("KOKORO_REPO_ID", "hexgrad/Kokoro-82M")
    vad_provider: str = _getenv("VAD_PROVIDER", "silero")
    silero_vad_threshold: float = _getfloat("SILERO_VAD_THRESHOLD", 0.5)
    silero_vad_min_silence_ms: int = _getint("SILERO_VAD_MIN_SILENCE_MS", 350)

    @property
    def websocket_base_url(self) -> str:
        if self.public_base_url.startswith("https://"):
            return "wss://" + self.public_base_url.removeprefix("https://")
        if self.public_base_url.startswith("http://"):
            return "ws://" + self.public_base_url.removeprefix("http://")
        return self.public_base_url


settings = Settings()

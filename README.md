# Live Voice Visitor Agent

工业园区访客车辆语音登记 Demo：访客拨打入口电话，Agent 在自然对话中采集车牌、来访单位、手机号、事由，登记后推送给门卫企业微信群。

## Architecture

```text
Caller
  -> Twilio Voice / SIP Trunk
  -> FastAPI /voice + /twilio/media
  -> VAD utterance buffer
  -> STT
  -> LangChain Agent
  -> JSONL visitor store
  -> WeCom group robot webhook
  -> Guard
```

The current implementation keeps speech adapters replaceable. Twilio Media Streams, μ-law audio framing, VAD buffering, visitor registration, and WeCom notification are implemented. Kokoro is loaded when the optional `kokoro` package is installed; otherwise the server falls back to silent placeholder audio so non-TTS paths remain testable.

Code is split by responsibility: `agent` contains the LangGraph workflow, visitor domain model, registration tools, and guard notification; `voice` contains the FastAPI/Twilio transport layer, audio framing, utterance buffering, STT, and TTS adapters.

## Setup

```bash
uv sync --dev
cp .env.example .env
```

For local Kokoro/Silero experiments, install optional voice dependencies:

```bash
uv sync --dev --extra voice-local
```

Required environment variables:

```bash
ANTHROPIC_API_KEY=...
AGENT_MODEL=anthropic:claude-sonnet-4-6
PUBLIC_BASE_URL=https://your-ngrok-url
GUARD_WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
OPENAI_API_KEY=...
TTS_PROVIDER=kokoro
KOKORO_LANG_CODE=z
AGENT_VOICE=zf_001
```

Run the voice server:

```bash
make voice
```

Expose it to Twilio:

```bash
ngrok http 8000
```

Configure the Twilio number or SIP trunk voice webhook to:

```text
POST https://your-ngrok-url/voice
```

Run checks:

```bash
make test
make lint
```

## Demo Notes

- Fast path target: greeting asks for plate, company, and reason in one sentence; Agent only asks for missing fields.
- A complete registration calls `register_visitor`, writes `data/visitors.jsonl`, and posts a WeCom text message.
- Repeat-visitor support uses `lookup_recent_visit(phone, plate_number)` to match by phone or plate number.

# Live Voice Visitor Agent

工业园区访客车辆语音登记 Demo：访客拨打入口电话，Agent 在自然对话中采集车牌、来访单位、手机号、事由，登记后推送给门卫企业微信群。

## Architecture

```text
Caller
  -> Twilio Programmable Voice Number
  -> FastAPI /voice + /twilio/media
  -> Silero VAD utterance buffer
  -> LangGraph SDK /runs/stream
  -> multimodal LangChain Agent
  -> JSONL visitor store
  -> WeCom group robot webhook
  -> Guard
  -> streamed text deltas
  -> Kokoro-82M TTS
  -> Twilio Media Streams audio
```

The current implementation keeps speech adapters replaceable. Twilio bidirectional Media Streams, μ-law audio framing, Silero VAD buffering, LangGraph SDK streaming, visitor registration, Kokoro-82M TTS, and WeCom notification are implemented. Caller audio is sent to the agent as a LangChain audio content block; there is no separate STT step.

Code is split by responsibility: `agent` contains the LangGraph workflow, visitor domain model, registration tools, and guard notification; `voice` contains the FastAPI/Twilio transport layer, audio framing, utterance buffering, LangGraph SDK client, VAD, and TTS adapters.

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
AGENT_MODEL=provider:model-with-audio-input
LANGGRAPH_API_URL=http://127.0.0.1:2024
LANGGRAPH_ASSISTANT_ID=agent
PUBLIC_BASE_URL=https://your-ngrok-url
GUARD_WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
TTS_PROVIDER=kokoro
KOKORO_LANG_CODE=z
KOKORO_REPO_ID=hexgrad/Kokoro-82M
AGENT_VOICE=zf_xiaoxiao
VAD_PROVIDER=silero
```

`AGENT_MODEL` must point at a LangChain chat model/provider that accepts audio content blocks. Add that provider package if it is not already in `pyproject.toml`.

Run the LangGraph server and voice server in separate terminals:

```bash
make run
make voice
```

Expose it to Twilio:

```bash
ngrok http 8000
```

Configure the Twilio Programmable Voice Number webhook to:

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

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

The current implementation keeps speech adapters replaceable. Twilio bidirectional Media Streams, μ-law audio framing, Silero VAD buffering, LangGraph SDK streaming, visitor registration, Kokoro-82M TTS, and WeCom notification are implemented. Caller audio is sent to the agent as an OpenAI-compatible `input_audio` content block; there is no separate STT step.

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
AGENT_MODEL=qwen3.5-omni-flash
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=sk-your-dashscope-api-key
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

For DashScope, keep the OpenAI-compatible base URL at `/compatible-mode/v1`. The model name in `AGENT_MODEL` must match the model identifier exposed by the provider; this repo uses LangChain's `ChatOpenAI` adapter with the configured OpenAI-compatible environment.

The Twilio voice path currently sends caller audio to the agent as a Base64 Data URL in an `input_audio` block. Use an audio-capable chat model such as `qwen3.5-omni-flash`; text-only local models need a separate STT step before the live phone flow.

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

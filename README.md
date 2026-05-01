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
make sync
cp .env.example .env
```

`Silero VAD` and `Kokoro-82M TTS` are part of the default runtime install.
For the local microphone-to-speaker websocket client, install the optional
audio-device dependency:

```bash
uv sync --dev
```

The default install includes `sounddevice`. On Ubuntu/Debian you also need the
system PortAudio library, for example:

```bash
sudo apt-get install portaudio19-dev
```

Required environment variables:

```bash
AGENT_MODEL=google_genai:gemini-2.5-flash
GOOGLE_API_KEY=your-google-api-key
OPENAI_API_KEY=
OPENAI_BASE_URL=
LANGGRAPH_API_URL=http://127.0.0.1:2024
LANGGRAPH_ASSISTANT_ID=agent
PUBLIC_BASE_URL=https://your-ngrok-url
TWILIO_WELCOME_MESSAGE=您好，请问车牌号多少，今天找哪家公司，什么事儿？
GUARD_WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
TTS_PROVIDER=kokoro
KOKORO_LANG_CODE=z
KOKORO_REPO_ID=hexgrad/Kokoro-82M
AGENT_VOICE=zf_xiaobei
VAD_PROVIDER=silero
```

`AGENT_MODEL` now accepts provider-prefixed model IDs such as
`google_genai:gemini-2.5-flash` or `openai:gpt-4o-mini`. Plain Gemini model
names remain supported for backward compatibility and are treated as Google
GenAI models.

When `AGENT_MODEL` uses the `openai:` prefix, the runtime uses LangChain's
`ChatOpenAI` adapter and honors `OPENAI_API_KEY` plus an optional
`OPENAI_BASE_URL` for OpenAI-compatible gateways. When `AGENT_MODEL` uses the
Google path, `GOOGLE_API_KEY` is used as before.

The Twilio voice path currently sends caller audio to the agent as a Base64 Data URL in an `input_audio` block. Use an audio-capable Gemini model such as `gemini-2.5-flash`; text-only local models need a separate STT step before the live phone flow.

Inbound calls first play the configured `TWILIO_WELCOME_MESSAGE` through TwiML `<Say>`, then switch into bidirectional Media Streams at `/twilio/media`.

Start the LangGraph server and voice server together for local testing:

```bash
make dev
```

If you want to run them separately:

```bash
make run
make voice
```

To verify the real `Silero VAD` and `Kokoro` integrations, run:

```bash
uv run python -m pytest tests/integration_tests/test_voice_stack.py -q
```

The `Kokoro` integration test performs a real synthesis call and may download
model files from Hugging Face on first run.

For a local realtime voice loop without Twilio, start the voice server and run:

```bash
uv run python scripts/live_ws_voice_chat.py
```

The local client connects straight to `/twilio/media` and now uses local VAD to
stream microphone audio continuously. Speak naturally and the client will open
and close turns automatically; `q` exits. If you want the old manual turn
controls, run `uv run python scripts/live_ws_voice_chat.py --manual-turns`,
then use `r` to start a turn, `s` to stop it, and `q` to exit. If you need
device indices first, run:

```bash
uv run python scripts/live_ws_voice_chat.py --list-devices
```

On WSL, `sounddevice` often cannot see default devices even when WSLg audio is
working. The client now falls back to `parec`/`paplay` against WSLg's
PulseAudio bridge. To inspect those device names, run:

```bash
uv run python scripts/live_ws_voice_chat.py --list-pulse-devices
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

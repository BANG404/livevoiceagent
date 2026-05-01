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

The current implementation keeps speech adapters replaceable. Twilio bidirectional Media Streams, optional DashScope ASR, μ-law audio framing, Silero VAD buffering, LangGraph SDK streaming, visitor registration, Kokoro-82M TTS, and WeCom notification are implemented. By default caller audio is sent to the agent as an OpenAI-compatible `input_audio` content block; when `STT_PROVIDER=dashscope`, the phone path first transcribes the utterance and then sends text to the agent.

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
STT_PROVIDER=
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_ASR_MODEL=qwen3-asr-flash
DASHSCOPE_ASR_LANGUAGE=
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

Leave `STT_PROVIDER` empty when `AGENT_MODEL` can directly understand audio, such as `google_genai:gemini-2.5-flash`. Set `STT_PROVIDER=dashscope` when the phone path should call Alibaba DashScope `qwen3-asr-flash` first and forward the transcript to a text-only model. `DASHSCOPE_BASE_URL` defaults to the China mainland endpoint; use the appropriate DashScope regional base URL if your API key is for Singapore or US regions.

Inbound calls immediately switch into bidirectional Media Streams at `/twilio/media`, and the agent generates the opening greeting from caller metadata plus recent-visit context.

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
- A complete registration calls `register_visitor`, writes `data/visitors.sqlite3`, and posts a WeCom text message.
- Repeat-visitor support preloads the caller's last 5 visits by phone into the agent's opening turn, so the agent can start with a direct revisit confirmation instead of a static Twilio greeting.

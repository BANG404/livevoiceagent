# Live Voice Visitor Agent

AI-powered voice visitor registration system for industrial parks. Visitors call a Twilio number and speak naturally with an AI Agent that collects license plate, company name, phone number, and visit reason, then notifies security via WeChat.

## Architecture

```
Caller ──► Twilio ──► FastAPI /voice + /twilio/media (WebSocket)
                            │
                     Silero VAD (utterance buffer)
                            │
                     LangGraph Agent (gemini / gpt-4o)
                     ├─ guard_notify ──► SQLite ──► WeCom webhook ──► Guard
                     └─ streamed text ──► Kokoro-82M TTS ──► Twilio audio

Guard ──► WeCom AI Bot ──► LangGraph guard_query ──► SQLite analytics
```

## Quick Start

```bash
# 1. Install dependencies
make sync
cp .env.example .env   # Fill in required environment variables below

# 2. Start locally (LangGraph dev server + FastAPI)
make dev

# 3. Expose to Twilio
ngrok http 8000

# 4. Configure Twilio webhook in console
#    POST https://<ngrok-url>/voice
```

Optional: Start WeChat guard query bot

```bash
make wecom-bot
```

Local microphone test (no Twilio required):

```bash
make ws-chat
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_MODEL` | LLM (provider:model) | `google_genai:gemini-2.5-flash` |
| `GOOGLE_API_KEY` | Google GenAI API key | — |
| `OPENAI_API_KEY` | OpenAI-compatible API key (for openai: prefix) | — |
| `OPENAI_BASE_URL` | Custom OpenAI gateway (optional) | — |
| `STT_PROVIDER` | Empty = model hears audio directly; `dashscope` = transcribe first | — |
| `DASHSCOPE_API_KEY` | Alibaba DashScope ASR key | — |
| `PUBLIC_BASE_URL` | Public URL accessible by Twilio | `https://xxx.ngrok.io` |
| `GUARD_WECHAT_WEBHOOK` | WeChat group bot webhook | — |
| `WECOM_BOT_ID` | WeChat AI Bot ID | — |
| `WECOM_BOT_SECRET` | WeChat AI Bot secret | — |
| `LANGGRAPH_API_URL` | LangGraph dev server | `http://127.0.0.1:2024` |
| `TTS_PROVIDER` | `kokoro` (default) or `silence` (testing) | `kokoro` |
| `VAD_PROVIDER` | `silero` (default) | `silero` |
| `VISITOR_STORE_PATH` | SQLite database path | `data/visitors.sqlite3` |

See `.env.example` for the complete list of variables.

## Testing

```bash
make test               # Unit tests
make integration-tests  # Integration tests
make lint               # Ruff checks
make format             # Auto-format with Ruff
```

## Development

The project uses `uv` for fast Python dependency management:

- **Agent Layer** (`src/agent/`): LangGraph workflows, domain models, registration tools, WeChat notifications
- **Voice Layer** (`src/voice/`): FastAPI/Twilio webhooks, audio handling, speech adapters, WebSocket streaming
- **Tests** (`tests/`): Unit tests and integration tests with shared fixtures

For more detailed architecture and development notes, see `CLAUDE.md`.

## License

MIT License - see `LICENSE` for details.

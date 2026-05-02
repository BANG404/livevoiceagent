# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live Voice Visitor Agent is a Python 3.13 voice-based visitor registration system for industrial parks. Visitors call a Twilio number, and an AI agent collects their vehicle plate, visiting company, phone number, and reason for visit through natural conversation. Registrations are stored in SQLite and pushed to WeChat for guards. The system also includes a separate "guard_query" assistant for guards to query visitor data through Enterprise WeChat.

## Architecture

The project splits code by responsibility:

- **Agent Layer** (`src/agent/`): LangGraph workflows, domain models, registration tools, and guard notifications
  - `graph.py`: Main visitor registration agent with `guard_notify` tool
  - `query_graph.py`: Guard-side query assistant with analytics tools
  - `domain.py`: `VisitorRegistration` model and `VisitorStore` (SQLite persistence with query methods)
  - `models.py`: Chat model factory supporting Google GenAI and OpenAI providers
  - `config.py`: Centralized environment variable loading
  - `guard_notify.py`: WeChat webhook notification

- **Voice/Transport Layer** (`src/voice/`): FastAPI/Twilio webhooks, audio handling, speech adapters
  - `app.py`: FastAPI app with `/voice` webhook and `/twilio/media` WebSocket for bidirectional streaming
  - `agent_stream.py`: LangGraph SDK client for agent calls with metadata (caller, call_sid)
  - `speech.py`: TTS (Kokoro-82M) and STT (DashScope ASR) adapters
  - `audio.py`: μ-law codec, VAD buffering (Silero), PCM16 handling
  - `live_ws_client.py`: Local microphone-to-speaker WebSocket client for testing

- **WeChat Bot** (`src/wecom_bot/`): Enterprise WeChat long-connection bot for guard queries
  - `assistant.py`: LangGraph client wrapper with stream event extraction
  - `main.py`: WebSocket connection manager
  - `bridge.py`: Message handling and formatting

- **Tests** (`tests/`): Unit tests in `unit_tests/`, integration tests in `integration_tests/`
  - Shared fixtures in `conftest.py` (AsyncIO backend)

## Data Flow

1. Caller dials Twilio number → `/voice` webhook returns TwiML with Media Stream URL
2. Twilio connects bidirectional audio to `/twilio/media` WebSocket
3. Voice server: captures μ-law audio → converts to PCM16 → Silero VAD buffers utterances
4. On speech closure: sends audio (or transcript if STT enabled) to LangGraph agent via SDK
5. Agent: generates reply, streams text deltas back
6. Voice server: segments text → Kokoro TTS synthesizes → sends μ-law audio back to Twilio
7. On complete registration: `guard_notify` tool persists to SQLite and posts WeChat message

Repeat-visitor optimization: Voice server fetches recent visits by caller phone, includes in agent opening context.

## Configuration

All settings load from `.env` via `src/agent/config.py`. Key variables:

- `AGENT_MODEL`: Provider-prefixed model ID (e.g., `google_genai:gemini-2.5-flash`, `openai:gpt-4o`)
- `GOOGLE_API_KEY` / `OPENAI_API_KEY`: LLM credentials
- `STT_PROVIDER`: Empty for audio-capable models; `dashscope` for text-only models with Alibaba ASR
- `LANGGRAPH_API_URL`: Dev server URL (`http://127.0.0.1:2024`)
- `PUBLIC_BASE_URL`: HTTPS URL exposed to Twilio (e.g., ngrok)
- `TTS_PROVIDER`: `kokoro` (default, includes 82M model download); `silence` for testing
- `VAD_PROVIDER`: `silero` (default); adjustable with `SILERO_VAD_THRESHOLD` and `SILERO_VAD_MIN_SILENCE_MS`
- `VISITOR_STORE_PATH`: SQLite database location (`data/visitors.sqlite3`)
- `GUARD_WECHAT_WEBHOOK`: Enterprise WeChat group bot webhook (optional)
- `WECOM_BOT_ID`, `WECOM_BOT_SECRET`: Credentials for guard query bot

See `.env.example` for all options.

## Build & Development Commands

Use the Makefile as the stable interface. All commands use `uv` (fast Python package manager).

### Setup
```bash
make sync          # Install runtime + dev dependencies
make install       # Install runtime dependencies only
```

### Running
```bash
make dev           # Start LangGraph dev server + FastAPI voice webhook together (via overmind)
make run           # Start LangGraph dev server only (port 2024)
make voice         # Start FastAPI voice webhook only (port 8000)
make wecom-bot     # Start Enterprise WeChat guard query bot
make ws-chat       # Local WebSocket voice chat client (no Twilio); speak naturally, VAD auto-closes turns
```

For local testing with specific caller phone: `make ws-chat CALLER=+8613800001234`

### Testing
```bash
make test                 # Run unit tests (fast, isolated)
make integration-tests    # Run integration tests (graph, cross-module)
pytest tests/unit_tests/test_configuration.py::test_visitor_store_latest_by_phone_or_plate -xvs  # Single test with output
```

### Code Quality
```bash
make lint          # Ruff checks
make format        # Ruff auto-format
```

## Key Implementation Details

### Agent Behavior

The visitor registration agent (`src/agent/graph.py`):
- Uses middleware to inject dynamic system prompt with current UTC time
- Supports preloaded recent visit history in opening context (5 most recent by caller phone)
- Requires four fields: `plate_number`, `company`, `phone`, `reason`
- Calls `guard_notify` tool when registration is complete
- Prefers direct confirmation for repeat visitors instead of repeating full questions

The guard query agent (`src/agent/query_graph.py`):
- Operates on guard-side, exposes four query tools: `count_visitor_registrations`, `search_visitor_registrations`, `find_busiest_visit_hour`, `list_repeat_visitors`
- Normalizes phone numbers and supports date/keyword filtering
- Defaults to Beijing time interpretation for relative dates ("今天", "本周")

### Speech Adapters

- **STT**: When `STT_PROVIDER` is empty, agent receives raw audio as `input_audio` content block (audio-capable models only). When `STT_PROVIDER=dashscope`, voice server transcribes first, then sends text.
- **TTS**: Kokoro (default) streams audio chunks for low latency. Falls back to alternate voices if primary fails. Silence adapter for testing.
- **VAD**: Silero VAD buffers frames, detects speech start/end, emits complete utterances when silence threshold reached.

### TextDeltaSegmenter

`src/voice/app.py` includes `TextDeltaSegmenter` which batches text deltas into chunks for TTS based on punctuation and max length (14–48 chars). Ensures natural pauses in speech synthesis.

### VisitorStore

SQLite-backed domain store (`src/agent/domain.py`) with:
- Async methods for I/O-bound operations (thread-pooled)
- Phone normalization (strips +86, dashes, spaces; uses last 11 digits for lookup)
- Query tools: filter by time range, company, phone, plate, reason keyword, caller, or free-text keyword
- Analytics: `count_visits`, `query_visits`, `busiest_hour`, `top_repeat_visitors`

### Guard Notify

`src/agent/guard_notify.py` sends visitor registration as formatted text message to WeChat webhook. Message includes plate, company, phone, reason, and entry timestamp.

## Testing Strategy

- **Unit tests** (`tests/unit_tests/`): Config loading, models, audio codecs, storage operations, tool invocation
- **Integration tests** (`tests/integration_tests/`): Full graph execution, audio recognition, cross-module workflows

Test voice stack integration (Silero VAD + Kokoro TTS):
```bash
uv run python -m pytest tests/integration_tests/test_voice_stack.py -q
```

Local WebSocket voice chat (no Twilio required):
```bash
uv run python scripts/live_ws_voice_chat.py --list-devices  # Inspect device names first
uv run python scripts/live_ws_voice_chat.py                 # Start; 'q' exits
uv run python scripts/live_ws_voice_chat.py --manual-turns  # Manual turn control (r/s/q)
```

On WSL, sounddevice may not detect hardware audio; script falls back to PulseAudio (`parec`/`paplay`).

## LangGraph Deployment

LangGraph graphs are defined in `langgraph.json`:
- `agent`: Visitor registration graph
- `guard_query`: Guard query assistant

Both graphs defined via:
- `agent.graph:graph` and `agent.query_graph:graph` respectively
- Python 3.13 runtime
- Wolfi image distro for deployments

Local dev server (port 2024):
```bash
langgraph dev --no-browser
```

## Code Style & Practices

- Follow existing Python style: 4-space indentation, type hints on public functions
- Use `snake_case` for functions/variables/modules; `PascalCase` for Pydantic models and classes
- Centralize configuration in `src/agent/config.py`; never hard-code secrets or URLs
- Prefer async/await with `asyncio.to_thread` for sync operations in async contexts
- Run `make format` before submitting changes

## Common Tasks

### Adding a new LLM provider

1. Extend `build_agent_model()` in `src/agent/models.py` to parse the provider prefix
2. Return the appropriate `BaseChatModel` subclass (e.g., `ChatClaudeAPI`, `ChatAnthropic`)
3. Test with `make test`

### Changing agent behavior

1. Modify system prompt in `src/agent/graph.py::build_system_prompt()`
2. Add/remove tools by updating the `tools` list in `create_agent()` call
3. Adjust tool implementations in same file or separate tool modules
4. Test with: `uv run python -m pytest tests/integration_tests/test_graph.py -xvs`

### Extending visitor registration fields

1. Add field to `VisitorRegistration` Pydantic model in `src/agent/domain.py`
2. Update SQLite schema in `VisitorStore._ensure_schema()` (use ALTER TABLE for migrations)
3. Update `guard_notify()` tool to accept new field
4. Update system prompt to request the field

### Debugging audio issues

- Check VAD thresholds and silence duration: `SILERO_VAD_THRESHOLD`, `SILERO_VAD_MIN_SILENCE_MS` in `.env`
- Verify TTS provider is available: `KOKORO_REPO_ID`, `KOKORO_LANG_CODE`
- Test with local client: `make ws-chat`
- Enable debug logging by setting `WECOM_LOG_LEVEL=DEBUG` for bot-side issues

### Integrating a new STT provider

1. Create subclass of `SpeechToText` in `src/voice/speech.py`
2. Implement `transcribe_pcm16()` method
3. Update `build_stt()` factory to instantiate based on `STT_PROVIDER` env var
4. Add credentials to `.env.example` and `src/agent/config.py`

## Testing Against Twilio

1. Copy `.env.example` to `.env` and fill in real credentials
2. Start dev server: `make dev`
3. Expose locally: `ngrok http 8000` (or use your preferred tunnel)
4. Configure Twilio webhook: `POST https://<your-ngrok-url>/voice`
5. Call your Twilio number; observe logs in dev terminal

## Documentation References

- Detailed architecture notes in `AGENTS.md`
- Vendor-specific docs in `DOCS/` (Kokoro, Silero VAD, Twilio, LangChain)
- Implementation notes in `TODO/` directory (work-in-progress items)


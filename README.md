# Live Voice Visitor Agent

工业园区访客语音登记系统：访客拨入 Twilio 号码，AI Agent 采集车牌、单位、手机、事由后推送企业微信门卫群。

## 架构

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

## 快速部署

```bash
# 1. 安装依赖
make sync
cp .env.example .env   # 填写下方必填变量

# 2. 本地启动（LangGraph dev server + FastAPI）
make dev

# 3. 暴露给 Twilio
ngrok http 8000

# 4. Twilio 控制台配置 Webhook
#    POST https://<ngrok-url>/voice
```

可选：启动企业微信查询机器人

```bash
make wecom-bot
```

本地麦克风测试（无需 Twilio）：

```bash
make ws-chat
```

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `AGENT_MODEL` | LLM（provider:model） | `google_genai:gemini-2.5-flash` |
| `GOOGLE_API_KEY` | Google GenAI 密钥 | — |
| `OPENAI_API_KEY` | OpenAI 兼容密钥（openai: 前缀时） | — |
| `OPENAI_BASE_URL` | 自定义 OpenAI gateway（可选） | — |
| `STT_PROVIDER` | 留空=模型直接理解音频；`dashscope`=先转文字 | — |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope ASR 密钥 | — |
| `PUBLIC_BASE_URL` | Twilio 可访问的公网 URL | `https://xxx.ngrok.io` |
| `GUARD_WECHAT_WEBHOOK` | 企业微信群机器人 Webhook | — |
| `WECOM_BOT_ID` | 企业微信 AI Bot ID | — |
| `WECOM_BOT_SECRET` | 企业微信 AI Bot Secret | — |
| `LANGGRAPH_API_URL` | LangGraph dev server | `http://127.0.0.1:2024` |
| `TTS_PROVIDER` | `kokoro`（默认）或 `silence`（测试） | `kokoro` |
| `VAD_PROVIDER` | `silero`（默认） | `silero` |
| `VISITOR_STORE_PATH` | SQLite 路径 | `data/visitors.sqlite3` |

完整变量列表见 `.env.example`。

## 测试

```bash
make test               # 单元测试
make integration-tests  # 集成测试
make lint               # Ruff 检查
```

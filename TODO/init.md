# Live Voice Agent 初始化方案

## 目标

使用 Twilio Voice/SIP Trunk 接入电话，服务端通过 Media Streams 获取 8kHz μ-law 音频；VAD 切分用户话语后送入 STT；LangChain Agent 负责自然对话和结构化访客登记；登记完成后推送到保安企业微信；后续将流式文本交给 Kokoro-82M TTS 合成后回写 Twilio 音频流。

## 当前已实现

- `voice.app`：FastAPI Webhook，包含 `/voice` TwiML 入口、`/twilio/media` 双向音频流入口、`/health` 健康检查。
- `voice.audio`：Twilio μ-law/base64 编解码、8kHz PCM16 帧处理、轻量能量 VAD 和话语缓冲。
- `agent.graph`：访客登记 Agent，工具包括 `register_visitor`、`lookup_recent_visit`、`calculator`，当前 UTC 时间写入系统提示词。
- `agent.domain`：`VisitorRegistration` 结构化模型和 JSONL 本地审计存储。
- `agent.guard_notify`：企业微信群机器人 Webhook 推送。
- `voice.speech`：OpenAI STT 适配器、可选 Kokoro TTS 适配器、缺少 Kokoro 时的静音 fallback。

## 待补强

1. Kokoro-82M TTS：确认目标机器的 Kokoro 安装方式、voice 名称和采样率，补充启动前健康检查。
2. Silero VAD：当前是能量阈值 fallback；生产环境应增加 Silero 适配器并保留 fallback。
3. 低延迟流式：当前按完整 utterance 处理；可改成 partial STT + LLM streaming + sentence-level TTS，压缩到 15-25 秒。
4. 回访识别：当前按手机号或车牌号查询历史；接入海康车牌事件后可按车牌优先匹配并在第一句话里确认。
5. 并发与可观测性：为 call_sid 增加 tracing、指标、录音片段采样和失败重试。

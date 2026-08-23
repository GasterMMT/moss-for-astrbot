# MOSS 语音插件（TTS / STT）for AstrBot

为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 接入 **MOSI 官方 MossAPI**（[https://api.mosi.cn](https://api.mosi.cn)），提供官方云端**单人语音生成**与**音频转写/多说话人转写**能力，自带现代化 WebUI 控制台页面。

> 官方 API 文档：[https://platform.mosi.cn/docs](https://platform.mosi.cn/docs) — 本插件所有接口契约均以此为准。

## ✨ 特性

- ☁️ **官方云端**：无需 GPU / 自建服务，纯 HTTP 调用 `https://api.mosi.cn`
- 🎧 **语音合成**：`POST /v1/audio/speech`，支持音色克隆、内置音色、`[pause X.Ys]` 停顿标记
- 🎙️ **音频转写**：`POST /v1/audio/transcriptions`，普通转写 + 多说话人转写（说话人分离、时间戳）
- 🎨 **克隆音色**：`POST /v1/audio/voices`，用本地参考音频一键克隆，自动填入 voice_id
- 🖥️ **WebUI 控制台**：联动状态、配置、克隆、一键同步、TTS/STT 连通性测试，随 AstrBot 深/浅色主题
- 🔁 **一键接入**：保存后自动创建 `moss_tts_cloud` / `moss_stt_cloud` 服务提供商，并切换 AstrBot 默认语音引擎
- 🪪 **配置组适配**：默认配置 + 所有「配置组」都会同步为 MOSS，杜绝历史提供商（如 MiMo）残留
- 🧩 **幂等热重载**：插件重载不冲突，AstrBot 启动/重载自动完成同步

## 🧭 工作原理

```
消息平台语音 ──► AstrBot STT (moss_stt_cloud)
                    │  POST https://api.mosi.cn/v1/audio/transcriptions（multipart file）
                    ▼
                大模型回复文本
                    │
                    ▼
              AstrBot TTS (moss_tts_cloud)
                    │  POST https://api.mosi.cn/v1/audio/speech（JSON）
                    ▼
                语音消息回复
```

## 📦 已注册的 Provider

| Provider 类型 | 名称 | 官方接口 | 模型 |
|---|---|---|---|
| `moss_tts_cloud` | MOSS 单人语音生成 | `POST /v1/audio/speech` | `moss-tts` |
| `moss_stt_cloud` | MOSS 音频转写 | `POST /v1/audio/transcriptions` | `moss-transcribe` / `moss-transcribe-diarize` |

## 🔑 官方接口契约摘要

### 认证
所有 `/v1` 接口使用 `Authorization: Bearer <API_KEY>`。API Key 在 [MossAPI 控制台](https://platform.mosi.cn)「API 密钥」页创建。接口**严格入参**：未知字段返回 `400 invalid_request_error`；无效 Key 常返回 `403 permission_error`。

### 单人语音生成 `POST /v1/audio/speech`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | 是 | `moss-tts` |
| `input` | string | 是 | 待合成文本；支持 `[pause X.Ys]`（0.1~10.0 秒） |
| `voice_id` | string | 是 | 音色 ID，只接受音色 ID（不接受 URL / base64 / 参考音频） |
| `version` | string | 否 | 模型变体，留空=默认（1.0 Pro）；1.5 Flash 为 `flash-20260626`（流式） |
| `response_format` | string | 否 | `mp3` / `wav`（推荐 mp3） |
| `delivery_method` | string | 否 | `audio`（默认，返回二进制）/ `url`（返回 JSON + 结果 URL） |
| `async` / `webhook_url` / `aigc_metadata` | — | 否 | 异步任务与 AIGC 标识（本插件暂不启用） |

### 音频转写 `POST /v1/audio/transcriptions`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | 是 | `moss-transcribe` / `moss-transcribe-diarize` |
| `diarize` | boolean | 否 | 多说话人转写建议 `true`，返回结构化 segments |
| `stream` | boolean | 否 | SSE 流式（本插件暂不启用） |
| `response_format` | string | 否 | `json` / `text` |
| `file` | file | 条件必填 | multipart 本地文件（最大 512 MB） |
| `file_id` | string | 条件必填 | `POST /v1/files` 返回的文件 ID |
| `url` / `audio_url` | string | 条件必填 | 公网音频 URL（不允许 localhost / 回环 / 私网） |

> 输入源四选一且只传一个；**不支持 audio_data / Base64 / 内联音频**。插件统一把平台语音转成 WAV 后走 multipart `file` 上传（需要系统安装 [ffmpeg](https://ffmpeg.org/)）。

### 音色

- `GET /v1/audio/voices`：音色列表
- `POST /v1/audio/voices`：克隆音色（multipart `audio_sample` + 可选 `name` / `description`）

### 其他
`POST /v1/files`（上传文件）、`GET /v1/models`（模型列表）、`GET /v1/audio/tasks/{task_id}`（异步任务查询）。

## 🧠 模型与版本

平台模型库的卡片名是「产品名」，API 里 `model` 是「接口/家族名」，变体由 `version` 选择：

| 平台模型卡 | API `model` | `version` |
|---|---|---|
| MOSS-TTS-v1.0-Pro | `moss-tts` | 留空（服务端默认） |
| MOSS-TTS-v1.5-Flash | `moss-tts` | `flash-20260626`（配合流式） |
| MOSS-TTSD | `moss-ttsd` | —（另端点，未接入） |
| MOSS-VoiceGenerator | `moss-voice-generator` | `moss-voice-generator-v1` |
| MOSS-Transcribe | `moss-transcribe` | 留空 或 `moss-transcribe-v1` |
| MOSS-Transcribe-Diarize-Pro | `moss-transcribe-diarize` | 留空 或 `v20260410-streamparam-20260703` |

> **日常留空 `version` 即可**，即 MOSS-TTS-v1.0-Pro 稳定版。

## 🚀 安装

插件要求 **AstrBot ≥ 4.16**（建议最新版）。将本仓库放入插件目录：

```bash
cd <AstrBot 目录>/data/plugins
git clone https://github.com/GasterMMT/moss-for-astrbot astrbot_plugin_moss_voice
```

或在 WebUI「插件市场 → 仓库安装」填写仓库地址。依赖仅 `httpx`（AstrBot 已内置）。

## ⚙️ 使用步骤

1. **获取 API Key**：[MossAPI 平台](https://platform.mosi.cn) → 控制台 → 「API 密钥」→ 创建；
2. **安装并重启 AstrBot**，打开插件管理 → **MOSS 语音（TTS/STT）** → 「settings」控制台页面；
3. 在控制台页面：
   - 填 API Key，选**音色 ID**（或「克隆音色」用本地参考音频生成自己的 voice_id）；
   - 点「**保存并同步**」——会自动创建 `moss_tts_cloud` / `moss_stt_cloud` 服务提供商，并把 AstrBot 默认语音引擎切到 MOSS；
   - 点「**测试 TTS**」听合成音、「**测试 STT**」验证转写回路；
4. 完成后群友发语音 → MOSS 转写 → 大模型回复 → MOSS 合成语音。

> **音色必填**：MOSS 官方 TTS 只接受 voice_id。可在控制台页面点选/克隆，或直接填官方内置音色。

## 🎨 官方内置音色

| 名称 | Voice ID |
|---|---|
| 轻快灵动女声（默认） | `806c9695-6160-404e-8722-4f788d935af3` |
| 曼波有口音版 | `c6c0a40a-ea82-4468-9a21-333d3c4a76f6` |
| 明太祖 | `f80b6698-0066-430b-88a0-f0fb8796db34` |
| VOX AKUMA | `ddc6e38b-6f55-4415-b21b-a88cad2cc1d9` |
| 李白 | `7662a8a1-700c-466a-b66b-57ece9e2e231` |
| 旁白Jake | `f9a1416b-d006-4b77-9581-8f0e8ec1e401` |
| 经验女教师 | `faf7f550-0627-4fc6-8db0-d3bfdad49358` |
| 少年感人声（男） | `fe85a513-9bf3-4ef7-aa0b-8b2d11e4db93` |
| 历史解说男声 | `0804710c-8e5e-4b67-acda-5785ef13c309` |
| 优雅英国女士 | `9d1e88e9-3b9c-4992-a414-7a1cb3ff7ab5` |
| 诗词朗读 | `2fdf194e-c16e-4587-9027-0d3464e09b4e` |
| 故宫纪录片 | `133bd03b-d717-4a55-8974-7ffc9afc1b51` |
| 东北虎哥 | `26838557-6890-4505-bc7c-e8198443a141` |
| 忧伤的秋 | `19411508-8731-4b68-901d-7e4b8a98e23f` |
| 三农农业旁白 | `944eb93b-3820-49f3-b2c0-4e37a31d1161` |

## 🚨 常见问题

- **provider 列表里没有 MOSS？** 插件要求 AstrBot ≥ 4.16；MOSS 条目带 `provider_type`，会显示在「服务提供商」页的 TTS/STT 分组。仍看不到则重启 AstrBot。
- **测试提示 403 permission_error？** API Key 缺失或无效；官方网关对无效 Key 常返回 403（不一定是 401）。
- **TTS 提示缺少 voice_id？** 官方接口必填，请选择内置音色或克隆音色。
- **AI 还在用别的（如 MiMo）语音？** 这是「配置组」优先级问题——该会话绑定的配置组默认值可能是别的提供商。插件同步会同时覆盖默认配置 + 所有配置组；也可用 `/provider tts <序号>` / `/provider stt <序号>` 手动切换。
- **STT 无法识别？** 需系统安装 ffmpeg；音频 ≤512 MB。
- **改音色没生效？** 改完点「保存并同步」，必要时重启 AstrBot 让实例重建。

## 📄 许可

**MIT License** — 见 [LICENSE](LICENSE)。

插件代码 MIT 许可；API 与模型归 [MOSI](https://platform.mosi.cn) 所有，接口契约以官方文档为准。插件架构参考 AstrBot 内置 Provider 实现（`astrbot/core/provider/sources`）。

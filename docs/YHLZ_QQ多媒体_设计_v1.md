# YHLZ QQ 多媒体（语音 / 图片 / 视频）设计 v1

> 状态：设计稿（未动工）。日期：2026-09-10。目标：让元亨在 QQ 上能**看懂图片、听懂语音、看短视频**，并能**回语音/图片**。

## 0. 结论（可行性）
| 能力 | 可行 | 依据 |
|---|---|---|
| 图片（入站） | ✅ 直接可行 | 本地 Gemma 启动含 `--mmproj`＝**视觉已开**；`backend/llm_engine.py` 已有 `image_url/base64` 多模态调用范式 |
| 语音（入站） | ✅ 直接可行 | QQ 语音(silk/amr)→wav→**SenseVoiceSmall** ASR（已集成）→文本 |
| 语音（出站） | ✅ 可行 | **Qwen3-TTS**（0.6B/1.7B 已集成）→wav→silk→`record` 段 |
| 图片（出站） | ✅ 可行 | NapCat `send_msg` image 段（本地文件/base64） |
| 视频 | ⚠️ 可行但受限 | 关键帧→视觉 + 音轨→ASR；需限时长/帧数/大小，时延高 |

## 1. 现状核实（证据）
- **视觉**：`llama-server … -m …\models\gemma4\gemma4-e4b-aggr-q4km.gguf --mmproj …\mmproj-gemma4-e4b.gguf`（Gemma-4 E4B 多模态）。模型在 `C:\Users\ACE_WAN——PROJECT\models\gemma4\`（**仓库外**）。
- **ASR**：SenseVoiceSmall（整段，cuda）已在 `tools/tts_test_start._transcribe` / `voice_dialog` 使用。
- **TTS**：Qwen3-TTS 0.6B/1.7B，`console_server._get_tts` 单例 + 顺序释放显存。
- **ffmpeg**：系统 PATH 无，但 `imageio_ffmpeg` 已装（自带 ffmpeg 二进制，可直接调）。
- **silk**：`pilk` 未装（QQ 语音编解码需要，纯 Python，可 pip）。
- **多模态代码**：`llm_engine.py` 有 `image_base64 → image_url` 调用；**当前主线 target 流式路径（orchestrator/llm_stream）未接图片**。
- **NapCat**：`enableLocalFile2Url=false` → 事件里媒体多为 `file` 标识，需用 OneBot API `get_image`/`get_record`/`get_file` 取本地文件（或临时开 `enableLocalFile2Url=true` 拿 URL）。
- **发现的问题（需先修）**：`yhlz_launcher.py` 的 `GEMMA/MMPROJ` 指向 `YHLZ\models\gemma4`（不存在），实际在 `C:\Users\ACE_WAN——PROJECT\models\gemma4`。**llama 掉线时 watchdog 会拉起失败**。

## 2. 架构

```
入站:  QQ 消息段
        ├─ text            → 原样
        ├─ image           → media_intake.download → cache/qq_media/…  → /turn(images=[...])
        ├─ record(voice)   → 下载 → 解码 wav16k → SenseVoice ASR → /turn(audio_text=…)
        ├─ video           → 下载 → ffmpeg 抽关键帧+音轨 → 视觉+ASR → /turn(images=[…], audio_text=…)
        └─ file            → 保存 cache/qq_media/，作为文本提及
     qq_bot ── POST /turn {text, channel, images[], audio_text} ──> daemon
                                                                    │
出站:  daemon 回复 ──> qq_bot ──> send_msg 段
        ├─ text            → 文本段
        ├─ 元亨产出/引用的图片 → image 段（file:// 本地路径）
        └─ 需要语音时       → Qwen3-TTS → wav → silk → record 段
```

## 3. 分阶段（建议顺序，每阶段可真机验收）
- **M1 图片入站**（最小闭环）：`get_image` → 存 `cache/qq_media/` → `/turn` 带 `images` → 本地 Gemma 视觉理解 → 回复。**先做，收益最高、改动最小。**
- **M2 语音入站**：`get_record` → silk/amr→wav → SenseVoice → 文本 → 回答。
- **M3 语音出站**：TTS→silk→`record` 段（可加"发语音"触发词或默认语音回复开关）。
- **M4 图片出站**：元亨生成/引用图片（图表、截图）→ image 段。
- **M5 视频**：`get_file` → 抽帧+音轨 → 视觉+ASR（限时长≤30s、帧数≤6）。
- **M6 记忆与留存**：媒体**摘要/转写文本**入库（原文件存 `cache/qq_media`，仅存引用，避免库膨胀）。

## 4. 关键设计点
- **`/turn` 扩展**：`{text, channel, images:[{path,mime}], audio_text, video:{frames[],audio_text}}`；向后兼容（缺省即纯文本）。
- **视觉调用**：`orchestrator` 增多模态分支，沿用 `llm_engine` 的 `image_url` 范式；图片 base64 内联给 llama-server（支持）。仅在有图片时启用，避免闲聊变慢。
- **资源（8G VRAM）**：ASR / TTS / llama **不共存** → 顺序释放（沿用现有 `release_sv`/`release_vram`）。视频额外加帧数与时长上限。
- **媒体存储**：`cache/qq_media/<yyyymmdd>/<sha1>.<ext>`，按天清理（保留 N 天，可配）。
- **安全/大小**：单文件上限（如 20MB）、下载超时；仅白名单主号私聊 + 群内 @元亨；出站仅发到来源会话。
- **依赖**：`pilk`（silk）、`imageio_ffmpeg`（已有）；可选 NapCat `enableLocalFile2Url=true` 简化取文件。
- **失败降级**：语音解码失败→回"没听清"；图片过大→缩图；视频超限→只取前 N 秒/首帧。

## 5. 风险与限制
- 视频最重、时延最高，**建议最后做**且强限幅。
- 视觉理解质量取决于 Gemma-4B，复杂/小字图可能不准（先做"描述性理解"，不做精确 OCR 承诺）。
- QQ 语音为 silk，需 `pilk`；若不可用退 `amr`+ffmpeg。
- NapCat 本地文件路径需可读（同机，OK）。

## 6. 验收标准
- 图片：私聊发一张图 → 元亨用文字描述内容（与图相符）。
- 语音：私聊发语音 → 元亨转述并回答。
- 出站语音：元亨按指令回一段语音（可播放）。
- 视频：发 ≤30s 短视频 → 元亨概述画面+说了什么。
- 回归：纯文本链路不受影响；`startup_test_*` 全绿。

## 7. 待定问题（需用户拍板）
1. **范围**：先只做**入站**（看图/听语音），还是一并做出站（回语音/图片）？
2. **优先级**：是否按 M1 图片 → M2 语音 → M5 视频 的顺序？还是先语音？
3. **群聊**：群里 @元亨 时是否也处理多媒体（同私聊）？
4. **出站语音**：默认不主动发语音，仅在你说"用语音回"时才发？音色用 0.6B 还是 1.7B？
5. **媒体留存**：`cache/qq_media` 保留几天（默认 7 天）？是否需要把图片也存进记忆（占空间）？

## 8. 前置修复（与多媒体无关但应顺带做）
- 修正 `yhlz_launcher.py` 的 Gemma 模型路径为 `C:\Users\ACE_WAN——PROJECT\models\gemma4\...`（或做成可配），否则 llama 掉线无法自动恢复。

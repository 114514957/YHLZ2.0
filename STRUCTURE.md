# YHLZ 2.0 项目结构总结

> 生成日期: 2026-08-03
> 依据当前仓库实际目录/代码整理, 用于快速了解项目全貌。

## 定位
语音数字人对话系统——本地 ASR + LLM + TTS + Live2D 虚拟形象,面向 RTX 4060 Laptop 8GB GPU 优化,提供 WebUI / 桌面挂件 / 语音 Demo 三种交互形态。

---

## 一、核心后端(`backend\`, FastAPI 服务, 端口 8000)

| 文件 | 职责 |
|---|---|
| `main.py` | FastAPI 主服务(57KB): SSE 对话、ASR/TTS/VAD/Live2D/记忆/WS 全量 API |
| `asr_engine.py` | 语音识别: FunASR SenseVoiceSmall(cuda) + 降噪/AGC/预增强 + 多方案 fallback |
| `tts_engine.py` / `tts\` | TTS 多引擎: `qwen3_customvoice`(主)、`edge`、`qwen3_tts`, manager 切换 |
| `llm_engine.py` | LLM: dashscope qwen-turbo 流式(SSE), 可切 deepseek |
| `vad_engine.py` | VAD 状态机(尾音判定已优化 2/1 帧 + 动态 hangover) |
| `config.py` | 环境配置读取(读 `.env`) |
| `audio_buffer.py` / `audio_enhancer.py` / `noise_suppression.py` / `echo_cancellation.py` | 音频链路处理 |
| `conversation_manager.py` / `context_manager.py` | 对话 / 上下文窗口管理 |
| `text_postprocessor.py` | 文本后处理 |
| `memory.py` / `memory_v2.py` / `data\memories*.db` | 记忆存储(SQLite) |
| `emotion_classifier.py` / `personality.py` | 情绪与人格 |
| `sync_manager.py` | 口型/表情同步 |
| `plugin_manager.py` / `tools.py` / `smart_tool_manager.py` | 插件 / 工具系统 |

## 二、语音对话 Demo(`对话DEMO\`)

- **`voice_chat_demo.py`**(49KB): 独立语音连续对话 Demo。
  - 链路: VAD 采集 → ASR → LLM 流式 → 句级切分 → 并行 TTS → 队列播放。
  - 已落地优化:
    - 插话不打断、排队播完追加(方案A);
    - 语音段超时入队不丢弃(方案C, 消灭"上一轮还在处理, 跳过本次语音段");
    - 相邻短段合并(碎片"对/然后/那个"合成一句);
    - 消费者互斥 + 历史顺序保持 + 上下文窗口 `history[-8:]`。
- `demo_webui.py` / `start_demo.bat`: Flask 版网页演示(端口 5050)。
- 测试脚本: `test_latency.py`、`test_comprehensive.py`、`smoke_test.py` 等。

## 三、Web 服务与桌面端

- `webui_server.py`(52KB): Flask 控制台(端口 8001 / 5060), 管理 avatar / 服务 / 记忆 / 工具 / API 代理。
- `backend\main.py` 的 `/ws/avatar`、`/ws/stream` WebSocket 做实时语音流。
- 桌面挂件与 GUI（2026-09-02 起统一归档到 `apps/`）: `apps/live2d_desktop_avatar.py`、`apps/live2d_pygame_avatar.py`、`apps/live2d_qt_avatar.py`、`apps/live2d_renderer.py`、`apps/avatar_main.py`、`apps/gui_*.py`、`apps/desktop_avatar/`（Electron 客户端）。
- 临时/诊断脚本（`tools/`）: `_quick_test*.py`、`_debug_clone.py`、`decompile_311.py`、`install_ffmpeg.py`、`pcm_latency_test.py`、`create_shortcut.py`。
- 历史交接文档移入 `docs/handover/`（HANDOVER_V4.5~V6.5）。

## 四、数据与资源目录

| 目录 | 用途 |
|---|---|
| `models/`、`checkpoints/`、`GPT-SoVITS/`、`index-tts/`、`sensevoice-finetuned/`、`whisper-finetuned-openai/` | 模型文件 |
| `assets/`、`desktop_avatar/` | Live2D 资源 |
| `webui_static/`、`webui_templates/index.html` | 前端 |
| `outputs/`、`recordings/`、`logs/`、`cache/`、`data/` | 运行产物 |

## 五、配置与插件

- `.env`: API Provider / 模型 / 音频参数(GPU bf16 优化)。
- `plugins\`: 4 个工具插件(`api_tools`、`file_tools`、`screen_monitor`、`utility_tools`), `plugin.toml` 声明。

## 六、规划文档(`下载物象\乱七八糟\`)

- 结构概览、架构总览、改进蓝图 v1.0、功能模块清单。
- 调研笔记: NachoBot / AIRI / NEKO。
- 迭代方案文档:
  - `YHLZ2.0_对话流畅度与检测优化方案.md`
  - `YHLZ2.0_插话追加续聊修正方案.md`
  - `YHLZ2.0_语音段超时丢弃修正方案.md`

## 七、运行链路速查

```bat
:: 后端
python -X utf8 backend\main.py          (端口 8000)
python -X utf8 -m uvicorn app:app --port 8001

:: 语音 Demo (必须 -X utf8, 防 Windows 编码崩溃)
python -X utf8 对话DEMO\voice_chat_demo.py

:: WebUI 控制台
python -X utf8 webui_server.py
```

## 八、当前运行进程注意(2026-08-03)

- 保留: `backend\main.py`(:8000)、`uvicorn`(:8001)、`clone_service.py webui`(:5060)。
- 语音 Demo / WebUI 演示进程均已在测试结束后关闭。

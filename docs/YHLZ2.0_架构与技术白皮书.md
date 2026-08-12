# YHLZ 2.0 项目架构与技术白皮书

> 版本: v1.0
> 生成日期: 2026-08-03
> 依据:当前仓库实际代码与数据,逐文件分析整理

---

## 目录

1. [项目概述](#一项目概述)
2. [总体架构](#二总体架构)
3. [目录结构总览](#三目录结构总览)
4. [后端核心引擎详解](#四后端核心引擎详解)
5. [语音对话链路与数据流](#五语音对话链路与数据流)
6. [延迟优化与并发设计](#六延迟优化与并发设计)
7. [前端与桌面端](#七前端与桌面端)
8. [直播子模块 live_stream](#八直播子模块-live_stream)
9. [插件与工具系统](#九插件与工具系统)
10. [数据存储与记忆体系](#十数据存储与记忆体系)
11. [配置体系](#十一配置体系)
12. [已知问题与待完善项](#十二已知问题与待完善项)
13. [技术白皮书:设计原则与关键技术](#十三技术白皮书设计原则与关键技术)
14. [运行手册与端口速查](#十四运行手册与端口速查)
15. [演进路线](#十五演进路线)

---

## 一、项目概述

### 1.1 定位

**YHLZ 2.0** 是一个面向个人桌面的**语音数字人对话系统**,实现"本地 ASR + 云端 LLM + 本地 TTS + Live2D 虚拟形象"的完整闭环。系统以 RTX 4060 Laptop 8GB GPU 为硬件基线进行显存与延迟优化,支持三种交互形态:

| 形态 | 入口 | 特点 |
|---|---|---|
| WebUI 控制台 | `start.bat` → `webui_server.py`(:5000) | 全功能管理面板,统一管控所有服务 |
| 桌面挂件(桌宠) | `live2d_qt_avatar.py` / `live2d_desktop_avatar.py` / Electron `desktop_avatar/` | 透明置顶 Live2D 形象,口型/表情实时同步 |
| 语音连续对话 Demo | `对话DEMO\voice_chat_demo.py` | 纯本地完整语音闭环,延迟可观测 |

### 1.2 核心特性

- **多模型管线**:FunASR SenseVoiceSmall(ASR)、Qwen3-TTS-12Hz-0.6B-CustomVoice / Edge-TTS(多引擎 TTS)、DeepSeek / 通义千问(LLM,可切换)
- **低延迟对话**:LLM 逐字符流式 + TTS 流式合成 + 首段 300ms 即开口的三层优化
- **对话体验优化**:插话排队不打断、语音段超时入队不丢弃、相邻短段合并、回声防自嗨
- **多模态同步**:口型(三正弦叠加)、表情(差分淡出)、视线状态机,毫秒级同步广播
- **插件化工具**:天气/搜索/文件/计算器/屏幕监测 4 大插件,直播扩展插件 3 个
- **认知型直播副模块**:事件驱动、能量/休息/冷场自律管理的虚拟主播方案

### 1.3 硬件基线

| 项目 | 规格 |
|---|---|
| GPU | RTX 4060 Laptop 8GB(显存按需加载/释放) |
| ASR 设备 | CUDA / FP16 |
| TTS 设备 | CUDA / bf16,CUDA graph 预热 |
| 统一采样率 | 16kHz(对话链路) |

---

## 二、总体架构

### 2.1 系统拓扑

```
                        ┌─────────────────────────────┐
                        │    webui_server.py (Flask)   │  :5000  WebUI 总控制台
                        │  服务管理/记忆/工具/API代理    │
                        └──────────────┬──────────────┘
                                       │ HTTP /api/* 代理(SSE 转发)
                        ┌──────────────▼──────────────┐
                        │   backend/main.py (FastAPI) │  :8000  后端核心
                        │  SSE /chat · WS /ws/avatar  │
                        │  WS /ws/stream · REST 全套  │
                        └──┬─────┬──────┬──────┬─────┘
                           │     │      │      │
         WS 口型/表情同步    │     │      │      │ HTTP 控制
        ┌───────────────────┘     │      │      │
        ▼                          │      │      ▼
┌───────────────┐    ┌──────────────┐    ┌──────────────────┐
│ 桌宠各实现      │    │  语音 Demo    │    │  浏览器 Live2D    │
│ Qt/pygame/    │    │ voice_chat_   │    │  viewer :8081    │
│ Electron/WebV │    │ demo.py       │    │  (live2d_viewer) │
└───────────────┘    └──────────────┘    └──────────────────┘
        │ 进程内直连引擎单例
        └──────────────┐
                       ▼
        对话DEMO/demo_webui.py (Flask) :5050  Demo 控制台
```

### 2.2 三种交互形态的数据路径

| 形态 | 路径 | 说明 |
|---|---|---|
| 语音 Demo | 麦克风 → 进程内引擎单例 → 音箱 | 不经过任何 HTTP 服务,进程内直连 `backend.*` |
| WebUI 控制台 | 浏览器 → webui_server(:5000) → backend(:8000) | 三层代理,SSE 流式渲染 |
| 桌面桌宠 | 桌宠 WS `:8000/ws/avatar` 收同步事件 + HTTP 控制 | 实时口型/表情/说话事件广播 |

### 2.3 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + uvicorn(单进程,异步) |
| 控制台 | Flask(:5000 / :5050) |
| ASR | FunASR(SenseVoiceSmall,`funasr>=1.0.0`)、openai-whisper 兜底 |
| TTS | faster-qwen3-tts(Qwen3-TTS-12Hz-0.6B-CustomVoice,真流式)、edge-tts、Qwen3-TTS-0.6B-Base(克隆) |
| LLM | openai SDK(AsyncOpenAI)对接 dashscope qwen-turbo / DeepSeek |
| VAD | 纯能量检测状态机(silero-vad 已移除依赖) |
| 音频处理 | librosa、scipy、rnnoise、noisereduce、webrtcvad(可选) |
| 桌面渲染 | live2d-py(v3,OpenGL)、PyQt5/QWebEngineView、pygame、Electron 28 + Pixi.js 6 + pixi-live2d-display |
| 直播 | pyvts(VTube Studio)、B站 WS 手写二进制协议、GPT-SoVITS(Gradio :9872) |

---

## 三、目录结构总览

```
YHLZ2.0/
├── backend/                    # 后端核心(FastAPI :8000)
│   ├── main.py                 # 主服务(1513 行):全部路由/WS/装配/播放线程
│   ├── config.py               # 配置单例(.env)
│   ├── asr_engine.py           # ASR(1110 行):多方案 fallback/多pass/流式增量
│   ├── asr_engine_qwen.py      # Qwen ASR 预留入口(小文件)
│   ├── llm_engine.py           # LLM 流式 SSE + LRU 缓存 + 多模态
│   ├── vad_engine.py           # VAD 能量状态机(打断判定)
│   ├── tts_engine.py           # TTS 兼容层(装配 TTSManager)
│   ├── tts/                    # TTS 多引擎包
│   │   ├── base.py             # 抽象基类 BaseTTSEngine
│   │   ├── manager.py          # 引擎注册/切换/自动回退
│   │   ├── qwen3_customvoice.py# 主引擎:CustomVoice 真流式 + CUDA graph
│   │   ├── qwen3_tts.py        # 语音克隆引擎
│   │   └── edge.py             # Edge-TTS 在线引擎(已实现未注册)
│   ├── audio_buffer.py         # 播放缓冲/打断/自播窗口/口型计算
│   ├── audio_enhancer.py       # ASR 预增强(降噪/AGC/压缩/均衡)
│   ├── noise_suppression.py    # 降噪链(AGC/谱减/DeepFilter 混合)
│   ├── echo_cancellation.py    # 回声消除(NLMS 自适应,备用能力)
│   ├── conversation_manager.py # 连续对话状态机/打断/回声过滤
│   ├── context_manager.py      # 上下文窗口/摘要/性格/记忆接口(部分 stub)
│   ├── text_postprocessor.py   # 文本清洗(繁简/错字/拼音/热词)
│   ├── emotion_classifier.py   # 情绪五分类 → 音色映射
│   ├── sync_manager.py         # 多模态同步事件总线(WS 广播)
│   └── data/                   # 记忆数据库/人格 JSON
├── 对话DEMO/                   # 语音对话 Demo
│   ├── voice_chat_demo.py      # 完整语音闭环(1166 行)
│   ├── demo_webui.py           # Flask 演示控制台(:5050)
│   ├── templates/demo.html     # 延迟追踪面板 + 日志
│   └── test_*.py               # latency/comprehensive/smoke 测试
├── webui_server.py             # Flask 总控制台(:5000,1268 行)
├── webui_templates/index.html  # 主控制台前端(2443 行,无框架)
├── webui_static/               # 静态资源(启动时自动创建)
├── live2d_*.py                 # 桌面挂件四种实现 + 渲染模块
├── desktop_avatar/             # Electron 桌宠(main.js/preload.js/pet.html)
├── desktop_avatar_py.py        # live2d-py 直渲染桌宠(非 stub)
├── updates/live_stream/        # 直播/虚拟主播子模块(见第八章)
├── plugins/                    # 工具插件 x4(api/file/screen/utility)
├── assets/live2d/              # 5 个 Cubism4 模型 + 浏览器查看器
├── models/ checkpoints/        # 模型文件(SenseVoice/silero_vad 残留等)
├── GPT-SoVITS/ index-tts/      # 语音克隆模型与示例
├── sensevoice-finetuned/ whisper-finetuned-openai/  # 微调模型
├── data/ outputs/ recordings/ logs/ cache/ memory/ prompts/  # 运行产物
├── .env / .env.example         # 环境配置
├── requirements.txt            # Python 依赖
├── start.bat                   # 主入口(自检依赖 → 启动 WebUI)
├── gui/                        # 空目录(历史遗留)
└── 下载物象/乱七八糟/            # 规划与调研文档(蓝图/研究报告/改进方案)
```

---

## 四、后端核心引擎详解

### 4.1 main.py — FastAPI 装配根

`backend/main.py`(1513 行)承担全部路由注册与全局单例装配:

**全局单例**:`asr_engine`、`tts_engine`(实为 TTSManager)、`llm_engine`、`vad_engine`、`audio_buffer`、`context_manager`、`conversation_manager`、`sync_manager`。

**生命周期(lifespan)**:
1. 打印配置 → 注入引擎到 conversation_manager 并 `start_conversation()`
2. 启动音频播放线程(`_audio_player_loop`:sounddevice 后台播放)
3. `sync_manager.start()`(10ms 事件处理循环)
4. 注册应急热键(Ctrl+Shift+R 清历史)
5. 关闭时依次停止播放线程 / sync_manager / `unload()` 三引擎(释放显存)

**API 端点全集**:

| 分类 | 端点 |
|---|---|
| 健康/统计 | `GET /health`、`/websocket-stats`、`/cache-stats` |
| 对话 | `POST /chat`(SSE 流式,核心)、`POST /interrupt`、`POST /clear-history` |
| 语音 | `POST /transcribe`、`POST /synthesize`、`POST /synthesize/stream`(NDJSON) |
| 性格 | `GET/POST /personality`、`POST /personality/reset` |
| VAD | `GET/POST /vad/config`、`POST /vad/detect`、`POST /vad/interrupt` |
| TTS | `POST /tts/engine`(运行时热切换)、`GET /tts/engines` |
| Live2D | `GET /live2d`(HTML)、`POST /live2d/{load,action,emotion,emotion-intensity,mouth-open,glow-color}`、`GET /live2d/{models,status}` |
| 同步 | `GET /sync/status`、`/sync/events` |
| 模块管理 | `GET /modules/status`、`POST /modules/start\|stop`(按需加载/释放显存) |
| 记忆 | `POST /memory`、`GET /memory/search`、`/memory/list`、`DELETE/PUT /memory/{id}` |

**WebSocket 协议**:

- **`/ws/avatar`**(桌宠同步):连接即注册进 sync_manager,服务端推送 `connected`/`mouth_sync`/`emotion_change`/`speech_start`/`speech_end`/`tts_chunk`/`ping`/`pong`;12 秒静默服务端主动 ping 保活。
- **`/ws/stream`**(流式语音对话):
  - `audio_chunk`:累积 3200 样本(≈0.2s)即送增量 ASR(executor 线程池),滑窗保留前 2/3 重叠,前缀 diff 下发增量 `asr_result`
  - `audio_end`:复位累积文本,回 `asr_done`
  - `chat_stream`:文本对话流,内置"清空/重置/重新开始"应急关键词;LLM 流式 + TTS 双通道(`text_chunk` + `audio_chunk`)下发
  - `interrupt` → `audio_buffer.interrupt()`
- **消息压缩**:`CompressedWebSocket` 对 >512 字节消息自动 zlib 压缩(level 6,前置 `\x00` 标记)。

**音频播放线程**:聚合缓冲至 2 秒(或首段满 `tts_first_chunk_min_ms` 即开口);播放中每 0.1s 切块计算口型开合度上报 sync_manager;仅在消费 done 哨兵后复位口型(被打断的流不产生 done)。

### 4.2 config.py — 配置中心

Pydantic `Config` 单例,`load_dotenv(override=True)` 强制以项目根 `.env` 为准。主要分组:

- **LLM**:`api_provider`(dashscope/deepseek)、`dashscope_model`(qwen-turbo)、`deepseek_model`、`vl_model`(qwen-vl-plus)
- **ASR**:`asr_model`(SenseVoiceSmall)、`asr_device`(cuda)、`use_fp16`、`asr_mode`(speed/balanced/accuracy)、beam/temperature/阈值三件套、多pass开关、音频增强开关
- **TTS**:`tts_engine`(qwen3-tts-customvoice)、`tts_max_chunk_length`(50)、情绪→音色开关
- **延迟**:`tts_first_chunk_min_ms`(300)、`tts_fallback_buffer_enabled`、`echo_filter_enabled`
- **上下文**:`max_context_tokens`(8000)、`summary_threshold`(7000)
- **音频**:`tts_buffer_ms`(10)、`sample_rate`(16000)

### 4.3 ASR 引擎(asr_engine.py,1110 行)

**主识别链**:SenseVoiceSmall(GPU/FP16)→ 多 pass 增强重识别 → 后处理清洗。

- **模型加载**:`cpu_then_gpu` / `direct_gpu` 双策略 + 每轮清显存重试(3 次);HF 端点智能选路(hf-mirror / modelscope / huggingface / fastgit 实测可达性与下载速度)
- **音频预处理链**:重采样 16k → `audio_enhancer.enhance()` → `noise_suppression.process_audio()` → 不足 8000 样本补零 → NaN/Inf 检测
- **长音频**:>30s 按 400000 样本块 + 80000 重叠滑窗切分拼接
- **多 pass 策略**:首次识别 `avg_log_prob < -0.3` 时用 beam≥15 高精度参数重识别,置信度提升才采纳
- **流式增量**:重叠 2400 样本、最小块 1600,前缀 diff 提取新文本
- **Fallback 链**:FunASR → whisper(medium→small→base→tiny)→ mock 模式
- **三档模式**:speed / balanced / accuracy 切换 beam、temperature、multi-pass

### 4.4 TTS 多引擎(tts/)

**架构**:`BaseTTSEngine` 抽象基类 → `TTSManager` 注册表实现"换引擎从改代码降为改配置"。

| 引擎 | 状态 | 说明 |
|---|---|---|
| `qwen3-customvoice`(默认) | 激活 | faster-qwen3-tts 真流式(每 8 token 产一块音频),CUDA graph 预热 + 端到端预热,首块延迟从 4-6s 压到 ~0.4s;音色 Vivian(24kHz) |
| `qwen3-tts` | 注册 | Qwen3-TTS-0.6B-Base 语音克隆(x-vector 说话人向量提取),非流式 |
| `edge` | 已实现未注册 | 在线免费,按标点 3~15 字智能分块,2048 字节粒度超低首包延迟,中文音色映射表 |

**管理器机制**:`activate(name)` 成功即激活;`auto` 逐个尝试;执行期异常自动回退到可用引擎。

### 4.5 LLM 引擎(llm_engine.py,422 行)

- 按 `api_provider` 建 `AsyncOpenAI`(dashscope 走 `compatible-mode/v1`);无 Key 时 `is_connected=False`
- **`generate_stream` 每收到 1 字符即 yield**(flush_threshold=1),首用 `_warmup()`("Hi",max_tokens=1)预连接
- `generate()` 整段生成 + LRU 缓存(1000 条 / TTL 300s / MD5 键)
- 多模态:`qwen-vl-plus` 分析 base64 图像(`generate_with_image`)
- 失败回退离线流式回复

### 4.6 VAD 引擎(vad_engine.py)

已移除 Silero 依赖,采用**纯能量检测 + 三态状态机**:

```
silence ──连续≥2帧有声──▶ speaking ──连续≥2帧无声──▶ hangover
hangover ──有声──▶ speaking(复位)
hangover ──连续≥dynamic_hangover帧无声──▶ silence
```

- **动态 hangover**:整段语音 <15 帧(短促语音)时 `dynamic_hangover = max(hangover_frames, 3)`,防短句切尾
- **噪声自适应**:静音态 RMS 入 30 帧滑动窗取中位数做 noise_floor(学习率 0.02),有效阈值 = `max(energy_threshold, noise_floor × 3.0)`
- 关键参数:`energy_threshold=0.015`、`frame_size=1600`、`min_voiced_frames=2`、`min_unvoiced_frames=2`

### 4.7 会话与上下文

**conversation_manager.py — 连续对话状态机**:
- 状态:`IDLE → LISTENING → THINKING → SPEAKING → INTERRUPTED`
- 流程:`handle_text_input → _update_topic`(关键词,最近 10 话题)→ 组装 system prompt → LLM 流式 → 每 chunk 触发 `_synthesize_and_play`(TTS 入 audio_buffer);被打断即停
- **回声过滤(蓝图1.5)**:`_is_self_echo()` 检查输入是否落在 audio_buffer "自播窗口"(播放前 2.5s + 播放后 6s),是则丢弃,防 AI 回应自己的声音
- 离线 fallback:LLM 未连接时按关键词模板句回复

**context_manager.py — 上下文窗口**:
- 组装:system(性格,由 personality.json 生成"你是元亨,用户的铁哥们…")+ 记忆提示 + 摘要 + 最近 10 条
- Token 计数:tiktoken `cl100k_base`,缺失时字符 ×0.5 估算
- **异步摘要**:累计 ≥7000 token 时调 LLM(temperature=0.3,≤100 字)生成摘要,清空历史仅留摘要,防溢出
- 性格读写 `backend\data\personality.json`;记忆接口当前为 stub(见 12 章)

### 4.8 情绪分类(emotion_classifier.py)

- 五分类:happy / calm / sad / angry / neutral,中文关键词规则表加权(2 字词权重 0.8,≥3 字词 1.2;感叹号≥2 个 ±0.5)
- 置信度 = 最高分 / 总分归一化;`resolve_voice_for_emotion` 低于阈值(0.5)回退默认音色
- 情绪→音色:happy→小艺、calm/neutral→晓晓、sad→晓墨、angry→云健

### 4.9 多模态同步(sync_manager.py)

- `SyncEvent` 入 `deque(maxlen=1000)`;`record_event()` 同步通知注册处理器 + WS 广播
- 事件类型:`mouth_sync` / `emotion_change` / `speech_start` / `speech_end` / `tts_chunk`
- 后台 `_process_loop` 10ms 轮询;口型数据由 main.py 播放线程每 0.1s 用 `audio_buffer.calculate_mouth_open()` 提供

### 4.10 音频链路四大模块

| 模块 | 作用 | 处理链 |
|---|---|---|
| `audio_enhancer.py` | ASR 预增强 | 噪声门 → 预加重(α=0.97) → RNNoise → 自适应谱减 → VAD 剪切 → 双频段 AGC(1k 以下目标 0.6/高频 0.4,限增益 10) → DRC(threshold 0.4, ratio 2.5) → RMS 归一化(0.15) → EQ(200Hz 高通 + 800~3000Hz 带通) → 60Hz 高通;另有快速模式 |
| `noise_suppression.py` | 降噪链 | AGC(20ms 帧) → noisereduce(非平稳,prop_decrease=0.6)或谱减法(alpha=2.0) → STFT 频段 EQ;模式 none/noisereduce/spectral/deepfilter/hybrid |
| `echo_cancellation.py` | 回声消除(备用) | NLMS 自适应滤波(4096 阶,逐样本)+ 频域分块(512)+ 谱减抑制 + 双讲检测(mic/ref > 0.3 跳过滤波);**当前未被主链路调用** |
| `audio_buffer.py` | 缓冲/打断/回声窗口 | deque 队列 + interrupt 清缓冲 + done 哨兵(被打断不产生)+ 自播窗口 + 口型计算(能量/0.5 clamp,alpha=0.3 平滑) |

### 4.11 文本后处理(text_postprocessor.py,671 行)

`clean_text()` 流水线:去空白 → 繁转简(OpenCC,缺则 1000+ 条内置对照表)→ 去重字符 → 去特殊字符 → 常见错字纠正(~200 条)→ 拼音纠错(~200 条)→ 热词替换 → 标点归一化。

置信度能力:`filter_by_confidence`(avg_logprob<-0.8 不可靠)、`extract_high_confidence_segments`、`postprocess()` 返回结构化诊断。

---

## 五、语音对话链路与数据流

### 5.1 主链路(Web 服务形态)

```
麦克风
  │ sounddevice InputStream
  ▼
vad_engine(能量状态机,判定打断)
  │
  ▼
asr_engine: audio_enhancer(降噪/AGC) → noise_suppression → SenseVoiceSmall
  │          → 多pass重识别 → text_postprocessor 清洗
  ▼
context_manager: 性格system + 摘要 + 最近10条 组装
  │
  ▼
llm_engine: SSE 流式(逐字符 flush)
  │
  ▼
切句器: 标点优先 / 逗号≥8字 / 50字上限(/chat) 或 12字触发/30字上限(/ws/stream)
  │
  ▼
tts_manager → qwen3_customvoice(流式,每8token一块)
  │
  ▼
audio_buffer(首段300ms即开口) → 播放线程(sounddevice)
  │                          └→ 每0.1s 口型开合度 → sync_manager
  ▼
sync_manager → WS /ws/avatar → 桌宠(口型/表情/说话状态)
```

### 5.2 语音 Demo 形态(voice_chat_demo.py)

**四类线程 + 四套队列的并发设计**:

| 线程 | 职责 | 关键点 |
|---|---|---|
| 录音线程 | sd.InputStream 回调,每 100ms 一帧 | 只做 VAD 与帧缓冲,**从不阻塞**;ASR 由 `_flush_speech` 另起 daemon 线程 |
| 播放线程 | OutputStream 回调连续无间隙播放 | 缓冲不足补静音;实时上报 AI 音量做回声遮蔽基准 |
| 处理线程 | `_on_speech_end` 拿锁后 `_handle_turn` | 同步 ASR + `asyncio.run` 跑 LLM/TTS 异步管线 |
| 排队段消费者 | `_process_pending_segments` | 消化插话/超时语音段,绝不丢弃 |

| 队列 | 内容 | 说明 |
|---|---|---|
| `Player._queue` | 播放音频序列 | threading.Queue |
| `Recorder._pending_segments` | 插话/超时段(deque maxlen=8) | 带 `_queue_lock` |
| `play_queue` | TTS 合成任务 ↔ dispatcher | asyncio.Queue,`(seq, audio, sr, is_end)` |
| `Recorder._preroll` | 预滚动 1s 环形缓冲 | ASR 前并入开头 1s,防丢首字 |

**三大对话体验机制**:

1. **插话不打断 / 排队追加(方案A)**:
   - 播放期录音暂停,但 VAD 持续;插话需满足音量遮蔽 `frame_rms > AI音量 × 1.6`(防把 AI 回声当插话)
   - 插话短段阈值 0.2s,播放结束判定后入队;播放完成回调启动消费者,dispatcher 保证插入顺序

2. **语音段超时入队不丢弃(方案C)**:
   - `_on_speech_end` 拿 `_processing` 锁超时 2s → `push_pending` 入队(无消费者则新起线程),消灭"上一轮还在处理,跳过本次语音段"

3. **相邻短段合并**:按 ts 顺序消化,相邻 <1.5s 且合并后 ≤50 字的段拼成一句,处理"对/然后/那个"碎片

**并行 TTS 与顺序保证**:
- LLM 每出一句 `create_task(_synth_one)`(min_segment_length=4 激进切句),各句独立合成
- `_play_dispatcher` 用 `next_seq` + pending 字典做 seq 排序:已结束段按序输出,未结束段流式提前输出,实现句间无卡顿;每段 finally 必发 `is_end` 哨兵防卡死
- barge-in 令牌 `_gen_token` 使旧 LLM/TTS 立即退出

**回声判定**:`_is_echo()` 检查插话与刚播 assistant 文本字符重叠 >60% 判回声。

**上下文**:`messages = [system] + history[-8:]`;barge-in 中断时不记录 assistant 回复并弹出 user 消息。

**延迟观测**:`LatencyTracker` 每轮输出 `vad_start → play_start` 端到端延迟报告,供 demo_webui 解析展示。

### 5.3 回声防自嗨双保险

1. **运行时窗口过滤**(主):audio_buffer 自播窗口(播放前 2.5s 余量 + 播放后 6s 余波),conversation_manager 丢弃窗口内输入
2. **AEC 备用能力**:NLMS 自适应滤波器 + 双讲检测模块已实现,未被主链路引用,可后续接入

---

## 六、延迟优化与并发设计

### 6.1 三层延迟优化

| 层 | 技术 | 效果 |
|---|---|---|
| LLM 层 | 逐字符 flush(flush_threshold=1)+ 预热 | 首 token 延迟最小化 |
| TTS 层 | 真流式(每 8 token 一块)+ CUDA graph 预热 + 端到端预热 | 首块延迟 4-6s → ~0.4s |
| 播放层 | 首段满 `tts_first_chunk_min_ms`(300ms)即开口渐进播放 | 心理感知首响最快 |

### 6.2 并发模型总结

- **backend**:FastAPI 异步 + `run_in_executor` 跑 ASR 增量;独立 sounddevice 播放线程;sync_manager 10ms 事件循环;LLM/TTS 协程流水线(生产者切句 → 消费者合成 → 缓冲)
- **语音 Demo**:线程 + 队列 + asyncio 混合(见 5.2),互斥锁 `_processing`(同刻只处理一句)+ `_pending_lock`(消费者互斥),**所有场景不丢弃语音段**
- **显存管理**:`/modules/start|stop` 按需加载/释放 ASR/TTS/VAD/LLM,适配 8GB 笔记本

---

## 七、前端与桌面端

### 7.1 WebUI 总控制台(webui_server.py :5000)

| 模块 | 能力 |
|---|---|
| avatar 管理 | 启动(优先 `live2d_qt_avatar.py`,fallback pygame/avatar_main;`FindWindowW("元亨桌宠")` 验证窗口)、停止、Win32 窗口控制(show/hide/move/topmost/lock/fade) |
| 服务管理 | backend(60s 就绪等待 + 最多 3 次自动重启监控)、live2d、voice_chat 的 start/stop/restart/start_all/stop_all |
| 记忆管理 | 清空/统计(session/knowledge/preference)/列表/增删 |
| 工具管理 | `/api/tools/list`、`/api/tools/call`(代理 :8000,**当前断链**,见 12 章) |
| API 代理 | `/api/chat/stream`(SSE 逐行转发)、health/personality/vision/live2d/tts/asr/config/logs |
| 系统信息 | psutil CPU/内存/磁盘 + nvidia-smi GPU;`/api/benchmark/pcm` 延迟基准 |

前端 `webui_templates/index.html`(2443 行,纯原生无框架):侧边栏 + 服务卡片 + 13 个功能页(Live2D 以 iframe 嵌 `:8081/live2d_viewer.html`)。

### 7.2 桌面挂件四种实现

| 实现 | 渲染方式 | 特点 |
|---|---|---|
| `live2d_qt_avatar.py` | PyQt5 + QOpenGLWidget(live2d-py v3),LWA_COLORKEY 透传 | 独立聊天窗、快捷键、12Hz 按键轮询 |
| `live2d_desktop_avatar.py` | QWebEngineView 加载 `:8081` 网页 + QWebChannel 桥 | 一体化启动器(自拉 backend),FaceTracker 摄像头面部捕捉,系统托盘 |
| `live2d_pygame_avatar.py` | pygame + OPENGL | 必须**先建窗口再 import live2d.v3**(DLL 冲突防护),手绘气泡菜单 |
| `live2d_renderer.py` | 纯渲染模块(参考实现) | 抽出口型/补间/表情差分淡出/视线管理器 |

**共有的口型与表情机制**(源于 live2d_renderer.py):
- 口型:三正弦叠加 `0.4sin(2.5φ)+0.3sin(1.8φ)+0.3sin(3.3φ)` 归一化 + RMS ×8 放大 + `LIPSYNC_OVERRIDE_THRESHOLD=0.001` 参数保护
- 表情:**基线三快照 + 差分淡出**(应用表情后计算参数基线差,~800ms 淡出回原态;口型参数不参与表情淡出)
- 视线:GazeManager(Drag 冷却)+ ease-out 补间;状态机 idle/viewing/thinking/replying

### 7.3 Electron 桌宠(desktop_avatar/)

- **技术栈**:Electron 28+ / Pixi.js 6 / pixi-live2d-display(Cubism 2/4/5),借鉴"桌面灵"架构
- **主进程 main.js**(546 行):无边框透明置顶(380×480, screen-saver 级置顶)、位置持久化(`%APPDATA%/yuanheng-avatar/avatar-config.json`)、点击穿透、三阶段拖拽 + 工作区 clamp、330ms 淡出关闭、游标追踪、单实例锁、显示器变化自适应
- **安全模型**:`contextIsolation:true` + `nodeIntegration:false` + contextBridge 暴露白名单 IPC
- **渲染进程 pet.html**(553 行):动态 CDN 加载库、点击 TapBody/TapHead 动作、30s idle 心跳、右键气泡菜单、字幕气泡、状态指示点(listening/speaking/thinking);对外暴露 `showSubtitle/setStatus/performMotion/performExpression` 集成 API

### 7.4 浏览器 Live2D 查看器(assets/live2d/live2d_viewer.html)

- 8 种情感光效系统(happy/sad/angry/surprised/anxious/tired/excited/neutral,主色 + 辉光 + 呼吸强度,easeInOutQuad 过渡)
- 外部控制双通道:`window.postMessage`(live2d_parameter/expression/motion/emotion/glow_color/mouth_open/speaking/gaze_state)+ `window.*` 函数
- 5 个 Cubism4 模型:hiyori / akari / wanko / tororo / hijiki(均含 vtube.json 可导入 VTube Studio)

---

## 八、直播子模块 live_stream

`updates/live_stream/` 是独立的**认知型虚拟主播方案**,事件驱动 + 异步任务 + 插件化。

### 8.1 架构

```
LiveStreamManager(中央调度:状态机/能量/冷场/话题/记忆)
   ├── set_plugins() ──▶ BilibiliLivePlugin(弹幕/礼物/SC 原始消息)
   │                     VTubeStudioPlugin(表情热键/参数注入/缓动/自动眨眼)
   ├── set_engines() ──▶ MouthSyncEngine(口型) / ExpressionController(表情)
   │                     TopicGenerator(话题) / CognitiveAvatarController(认知)
   ▼
events.py 事件工厂: is_allowed(权限+价格门槛) → normalize → format(模板) → to_payload
   ▼
tts_service.enqueue_text() ── TTS 双队列(HIGH/NORMAL)──▶ GPT-SoVITS Gradio(:9872)
```

### 8.2 直播工作流(live_stream_manager.py)

- **状态机**:`IDLE → PREPARING → LIVE ⇄ BREAK → ENDING → ENDED`
- **B站事件解析**:手写 WS 二进制协议(16B 头 + body,zlib 解压,30s 心跳),事件类型:弹幕/SC/礼物/连击/舰长/进场/点赞;SC/礼物/舰长 = HIGH 优先级 TTS 播报
- **弹幕回复**:ExpressionController 关键词+emoji 打分 → VTS 切表情;长度 >5 时 LLM 生成 ≤30 字回复,2 秒延迟防刷屏
- **长直播自律管理**:
  - 能量系统:LIVE 每 60s 衰减 0.005,休息恢复 0.02/分钟,<20% 自动休息
  - 自动休息:每 30 分钟强制休息
  - 冷场检测:30s 无弹幕自动生成话题
  - 自动话题:每 300s 主动(topic_generator 6 大类 60+ 话题,按弹幕关键词推断类型)
- **直播记忆回写**:结束后保存时长/弹幕数/礼物数/热门话题到主项目记忆库(category="live")

### 8.3 认知控制器(cognitive_avatar_controller.py)

"认知状态 → 虚拟形象表现"的差异化亮点:

- **8 种认知反应**:NEUTRAL/ALERT/FOCUSED/SURPRISED/CALM/EXCITED/THREATENED/BEAUTY_AWE
- **三层判定**:系统状态映射 → 张力类型(危机→THREATENED 优先于美学→BEAUTY_AWE)→ 认知带宽
- **表现映射**:THREATENED→angry 表情、BEAUTY_AWE→surprised、EXCITED→excited+wave_hand、ALERT→surprised+blink
- **注意力头部动作**:视觉/音频注意力权重(5 帧滑动平均)→ HeadX/HeadY + easeBoth 缓动
- **跨模态涌现**:多模态共鸣→BodyAngle 摇摆;空间感知激活→HeadX 扫视
- **规则引擎**:6 条按优先级(10~1)排序,支持动态增删

### 8.4 TTS 服务(tts_service.py,借鉴 bili_voice)

- 双线程双队列:HIGH 队列满时挤掉 NORMAL(evict 回调);`threading.Condition` 同步
- GradioClient 直连 GPT-SoVITS(:9872):`/config` 发现 API id,`/change_sovits_weights` 热切换权重,`/inference` 合成(20+ 参数)
- 播放 winsound → 回退 ffplay;dB 增益限幅 -60~+24;状态回传 pending/playing/done/cancelled

### 8.5 插件

| 插件 | 能力 |
|---|---|
| `bilibili_live` | 弹幕/礼物监听(手写 B站 WS 协议)+ 弹幕发送(`api.live.bilibili.com/msg/send`) |
| `vtube_studio` | pyvts 认证、表情热键、`set_parameter_with_easing` 6 种缓动 100Hz 插值、自动眨眼(3s 间隔)、ModelLoaded 订阅 |
| `live_control` | 统一入口:start/end/break/resume/send/get_status/get_stats/set_expression/config |

---

## 九、插件与工具系统

### 9.1 架构

插件继承 `backend.plugin_sdk.NekoPluginBase`,`@plugin_entry(id,name,description,parameters)` 声明工具,返回 `Ok(value)/Err(error)` 结果对象;`plugin.toml` 声明(entry 指向 `plugins.xxx:Class`,SDK 版本 `>=0.1.0,<0.2.0`,enabled/auto_start)。

> ⚠️ 注意:`plugin_sdk.py` / `plugin_manager.py` / `tools.py` / `smart_tool_manager.py` 当前为**反编译还原的 stub 空壳**(见 12 章),插件实现本身完整,但调度层待重建。

### 9.2 工具插件清单(plugins/)

| 插件 | 工具 | 说明 |
|---|---|---|
| `api_tools` | `get_weather`(wttr.in)、`web_search`(DuckDuckGo) | requests 超时 10s |
| `file_tools` | `read_file`(超 1000 字截断)、`write_file`(append)、`list_files`(带图标) | 无路径沙箱限制 |
| `utility_tools` | `calculator`(正则白名单 `^[\d\s+\-*/().%^]+$` 后 eval)、`get_time/get_date`、`set_reminder`(守护线程) | |
| `screen_monitor` | `start/stop_monitor`、`capture_now`、`analyze_now`、`get_status`、`get_analysis_history`、`set_config` | 30s 截屏 + 120s 分析;识别出"视频/游戏/文档/网页"时按 300s 冷却**主动搭话**(push_message);依赖 vision_engine(stub)与 `llm_engine.generate_with_image` |

---

## 十、数据存储与记忆体系

### 10.1 人格数据(backend/data/personality.json)

- 角色:元亨,用户的"铁哥们";性格词:义气/随和/爽快
- 说话风格 casual、兄弟腔、口头禅(收到哥们/哟/中/没毛病/妥了)
- 由 context_manager 读入生成 system prompt

### 10.2 记忆数据库现状(重点确认)

**源码缺失**:`memory.py` / `memory_v2.py` 无源文件,pyc 反编译确认为 stub(`add_long_term_memory` 返回 `"memory_stub"`,`get_relevant_memories` 返回空)。当前运行中记忆接口为空壳。

**残留数据库展示了曾经/设计的完整结构**:

`memories.db`(81KB,13 条记忆,v1 真实历史数据):
- `memories`:id/content/category/importance/created_at/last_accessed/**embedding**(100+ 维向量,曾有向量检索)/**decay_factor**(遗忘衰减)/source_conversation/is_pledge/pledge_deadline/pledge_status/context_tags/related_memory_ids/iteration_count
- `memory_relations`:记忆关系图谱(source/target/relation_type)
- `context_scenarios`:场景化记忆过滤(trigger_keywords/memory_filter/priority)

`memories_v2.db`(45KB,5 表设计完整但全空):
- `long_term_memories`:v1 基础上新增 emotion_tag、consolidated_into(记忆整合)
- `memory_relations`:多 weight 列
- `contacts`:姓名/关系/关系分/时间线/记忆关联(15 列)
- `personality_profiles`、`emotion_records`:人格画像与情绪记录

**结论**:记忆管线(v1 向量检索 + v2 多实体)曾真实存在,现已被 stub 占位,真实实现需按上述 schema 重建。

### 10.3 其他运行产物

| 目录 | 内容 |
|---|---|
| `outputs/` | TTS 音频产物 |
| `recordings/` | 录音 |
| `logs/` | webui/backend 日志 |
| `cache/` | 运行缓存 |
| `data/test_sandbox.txt` | 沙盒写入测试文件 |

---

## 十一、配置体系

### 11.1 .env 键名总览(不含密钥值)

```
API_PROVIDER               # dashscope / deepseek
DEEPSEEK_API_KEY / BASE_URL / MODEL
DASHSCOPE_MODEL            # qwen-turbo(Key 从系统环境变量读)
ASR_MODEL / ASR_DEVICE / USE_FP16 / USE_KV_CACHE / ASR_FAST_MODE
TTS_ENGINE / TTS_MAX_CHUNK_LENGTH / TTS_FIRST_CHUNK_MIN_MS / TTS_FALLBACK_BUFFER_ENABLED
MAX_CONTEXT_TOKENS / SUMMARY_THRESHOLD / TTS_BUFFER_MS / SAMPLE_RATE
```

### 11.2 配置文件清单

| 文件 | 用途 |
|---|---|
| `.env` | 后端引擎配置(唯一权威) |
| `gui_config.json` / `assets/live2d/gui_config.json` | 桌宠配置 |
| `webui_config.json`(运行时生成) | WebUI 配置 |
| `launcher_config.json`(运行时) | live2d_desktop_avatar 启动器 |
| `updates/live_stream/config/*.json` | 直播模块配置(开关/房间/Cookie/VTS) |
| `plugins/*/plugin.toml` | 插件声明(默认 enabled 视插件而定) |

---

## 十二、已知问题与待完善项

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| 1 | `conversation_manager.handle_ws` 不存在 | main.py:1499 → `/ws` 路由 | 调用必抛 AttributeError,`/ws` 端点待修复或移除 |
| 2 | 记忆系统为 stub | context_manager 内联接口 | 接口与 DB schema 已定,`add_long_term_memory` 等返回 `"memory_stub"`,需按 memories_v2.db 设计重建 |
| 3 | 插件调度层为 stub | plugin_sdk/plugin_manager/tools/smart_tool_manager | 反编译还原的空壳;main.py 无 `/tools` 端点 |
| 4 | webui 工具代理断链 | webui_server.py `/api/tools/*` → `:8000/tools` | 目标端点不存在 |
| 5 | screen_monitor 依赖 vision_engine stub | 插件 | 截屏分析实际无法运行 |
| 6 | Edge-TTS 引擎未注册 | tts/edge.py | 实现完整,`_build_default_manager` 未注册 |
| 7 | echo_cancellation 未接入主链路 | 模块 | AEC 是备用能力,当前靠自播窗口过滤 |
| 8 | 顶层多个启动脚本为 stub | avatar_main/gui_main 等 12 个 4 行占位 | 真实入口:start.bat / voice_chat_demo / desktop_avatar |
| 9 | `webui_static/`、`prompts/`、`memory/`、`gui/` 为空 | 目录 | 运行时生成或历史遗留 |
| 10 | `/memory/{id}` DELETE/PUT 为占位 | main.py | 不落库 |

---

## 十三、技术白皮书:设计原则与关键技术

### 13.1 设计原则

1. **低延迟优先,渐进式开口**:对话延迟优化的核心思想不是"全部生成完再播",而是"边说边听、边想边播"——LLM 逐字符、TTS 逐块、播放首段 300ms 即开口,三层流水线把用户感知延迟压到最小。
2. **多级 fallback 永不静默失败**:ASR(FunASR→whisper→mock)、TTS(引擎级自动回退)、LLM(离线模板回复),任何一环故障都给出可用输出。
3. **对话体验 > 严格时序**:插话不打断、语音段超时入队不丢弃、短段合并——"宁可排队听完,不可丢用户的话"。
4. **回声自防**:自播窗口过滤 + NLMS AEC 双保险,AI 不回应自己的声音。
5. **显存按需**:8GB 笔记本上引擎模块可独立加载/释放,GPU 资源用在哪层完全可控。
6. **引擎可插拔**:TTS 抽象基类 + 注册表、LLM provider 切换、VAD 从 Silero 迁移纯能量的演进路径,均体现"配置驱动,代码不动"。
7. **表现层认知化**:直播子模块将"认知状态"逐层映射为表情/动作/头部运动,数字人从"会说话"走向"有状态"。

### 13.2 关键技术点

| 技术 | 说明 |
|---|---|
| 流式增量 ASR | 3200 样本触发 + 2/3 重叠滑窗 + 前缀 diff,识别文本随说话实时输出 |
| 动态 VAD 尾音保护 | 短句自动加 hangover,防切尾;噪声地板自适应 |
| 三正弦口型模型 | 不同频率正弦叠加模拟自然开合,平滑系数 0.3 |
| 表情差分淡出 | 表情只改变"与基线的差",800ms 淡出恢复,口型参数豁免 |
| 认知→表现映射 | 系统状态/张力/带宽/注意力 → 表情/动画/HeadX/Y 缓动 |
| NLMS 回声消除 | 4096 阶逐样本自适应 + 双讲检测,ERL 估计 |
| 双频段 AGC | 1k 以下目标 0.6、高频 0.4,限增益 10dB,适配语音频谱 |
| CUDA graph 预热 | TTS 流式首块延迟 4-6s → 0.4s |
| zlib 压缩 WS | >512B 消息自动压缩,降低桌宠同步带宽 |
| seq 排序 dispatcher | 并行 TTS 结果按序输出,句子间零卡顿 |

### 13.3 性能基线(实测/设计目标)

| 指标 | 目标 |
|---|---|
| TTS 流式首块延迟 | ~0.4s(CUDA graph 预热后) |
| 播放首响门槛 | `tts_first_chunk_min_ms` = 300ms |
| 插话响应 | 播放期音量遮蔽 >1.6× 判定,锁超时 2s 转排队 |
| 长直播 | 3-4 小时(能量/休息/冷场/话题自律) |
| 弹幕回复延迟 | 2s 防刷屏节流 |

---

## 十四、运行手册与端口速查

### 14.1 启动方式

```bat
:: 主入口(WebUI 总控制台 :5000,自动装依赖/建目录/开浏览器)
start.bat

:: 语音 Demo(必须 -X utf8 防 Windows 编码崩溃)
python -X utf8 对话DEMO\voice_chat_demo.py
python -X utf8 对话DEMO\demo_webui.py          (:5050 控制台)

:: 后端直启
python -X utf8 backend\main.py                 (:8000)

:: 桌宠
python live2d_qt_avatar.py
python live2d_desktop_avatar.py
cd desktop_avatar && npm start                 (Electron)

:: 直播模块(配置 + 插件启用后)
python updates\live_stream\install_deps.py
```

### 14.2 端口速查

| 端口 | 服务 | 协议 |
|---|---|---|
| 5000 | webui_server.py Flask 主控制台 | HTTP /api/* + SSE |
| 5050 | demo_webui.py Demo 控制台 | HTTP + SSE 日志 |
| 8000 | backend/main.py FastAPI | HTTP + WS /ws/avatar /ws/stream |
| 8081 | live2d_desktop_avatar 内嵌静态服务器 | HTTP(live2d_viewer.html) |
| 9872 | GPT-SoVITS WebUI(live_stream TTS) | Gradio |
| 18765 | avatar 备用 Live2D 查看器 | HTTP |

### 14.3 进程关系

- WebUI(5000)以子进程管理 backend(8000)/live2d,带 60s 就绪等待 + 最多 3 次自动重启
- live2d_desktop_avatar 会自拉 backend(uvicorn 启动 `backend.main:app`)
- voice_chat_demo 与 backend 引擎**进程内直连**,不经过任何服务端口
- demo_webui(5050)以子进程管理 voice_chat_demo,SSE 转发日志

---

## 十五、演进路线

### 15.1 短期(恢复完整功能)

1. 重建记忆系统:按 `memories_v2.db` 的 5 表 schema 实现 v2 记忆管线(向量检索 + 遗忘衰减 + 联系人图谱)
2. 重建插件调度层:实现 plugin_sdk/plugin_manager/tools,恢复 main.py `/tools` 端点,接通 webui 工具代理
3. 修复 `/ws` 路由的 `handle_ws` AttributeError
4. 注册 Edge-TTS 引擎,完善 TTS 引擎切换面

### 15.2 中期(体验深化)

1. 接入 echo_cancellation 到主链路(自播窗口 + AEC 双保险落地)
2. vision_engine 实现,screen_monitor 主动搭话能力生效
3. 情绪分类升级零样本模型(预留 mDeBERTa)
4. 记忆→人格动态演化(记忆影响性格与话题)

### 15.3 长期(智能化)

1. PROACTIVE/ACTIVITY 开关落地:数字人主动发起话题(蓝图 4.1)
2. 直播子模块与主项目融合:认知控制器的张力/注意力输入接入桌宠
3. 多模态融合:视觉感知进入对话上下文(系统已具备 `generate_with_image`)
4. 端到端人格一致性:声音克隆(语音克隆引擎已具备)+ 情绪音色 + 表情差分统一调度

---

*文档基于 2026-08-03 仓库实际代码与数据生成,后续重构后需同步更新。*

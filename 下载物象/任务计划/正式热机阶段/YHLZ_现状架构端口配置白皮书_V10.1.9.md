# YHLZ 现状架构 · 端口 · 配置白皮书（V10.1.9）

> 版本：V10.1.9（热机阶段 · Real-time AI Companion Runtime）
> 生成日期：2026-08-12
> 数据来源：backend/config.py 全量 + .env 实读 + netstat 端口实测 + V10.1.9 基础设施审计结论
> 关联文档：`YHLZ_V10.1.9_基础设施可靠性审计报告.md`（热机时期改进\）
> 项目根：`D:\YHLZ2.0`；解释器：`venv\Scripts\python.exe`

---

## 一、当前运行状态快照（2026-08-12 实测）

| 服务 | 端口 | 状态 | 说明 |
|---|---|---|---|
| WebUI 服务编排 | 5000 | ⚪ 未运行 | `python webui_server.py` 一键拉起 |
| 后端 API | 8000 | ⚪ 未运行 | `python backend/main.py`（FastAPI + uvicorn） |
| Live2D 桌宠 | 8081 | ⚪ 未运行 | `live2d_qt_avatar.py`（WebUI 内启停） |
| 审计隔离实例 | 8900 | ⚪ 未运行 | V10.1.9 审计脚本专用，勿与生产复用 |

> ⚠️ 本机所有 YHLZ 服务当前均处于停止状态（netstat 实测无监听、无 python 进程）。
> 启动方式见 §三。

---

## 二、架构总图（现状 · 接线状态标注）

```
┌────────────────────────── 前端层 ──────────────────────────┐
│ webui_server.py :5000 (服务编排/API代理/SSE透传)            │
│ webui_templates/index.html (SSE解析/顺序播放/状态栏)        │
│ frontend/ (桌面壳: runtime状态机/startup 9步/avatar)        │
│ live2d_qt_avatar.py :8081 (桌宠渲染)                        │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP :8000 / SSE / WebSocket /ws
┌──────────────────────────────▼──────────────────────────────┐
│ API 层  backend/main.py (3855 行, FastAPI)                  │
│ 路由: /health /chat(SSE) /transcribe /synthesize(+stream)   │
│       /interrupt /clear-history /personality* /voice* /vad* │
│       /tts* /live2d* /sync* /modules* /memory* /agent*      │
│       /perception* /understanding* /vision* /action* /ws    │
└──────────────────────────────┬──────────────────────────────┘
        ┌──────────────────────┼──────────────────────┐
┌───────▼────────┐ ┌───────────▼──────────┐ ┌─────────▼─────────┐
│ 对话运行时层    │ │ 模型层                │ │ 语音层            │
│ conversation_  │ │ llm_engine.py ✅     │ │ tts_engine + tts/ │
│  controller ✅ │ │  (无超时/无重试⚠)     │ │  ✅(全链静音回退⚠) │
│  (状态机11态)  │ │ model_pool/ ❌未接线  │ │ asr_engine ✅     │
│ context_manage │ │ token_opt/ ❌未接线  │ │  (mock幻觉⚠)      │
│  er ✅(无锁⚠)  │ │ memory_policy ❌未接 │ │ vad_engine ✅     │
│ input_aggregat │ │ 线 (显存仲裁)        │ │  (打断bug⚠)       │
│  or ❌未接线    │ │                      │ │ audio_buffer ✅   │
│ conversation_  │ │                      │ │  (无界队列⚠)      │
│  manager(旧)⚠  │ │                      │ │ echo_cancel ❌死码│
└────────────────┘ └──────────────────────┘ └────────────────────┘
        ┌──────────────────────┼──────────────────────┐
┌───────▼────────┐ ┌───────────▼──────────┐ ┌─────────▼─────────┐
│ Agent 认知层    │ │ 独立子系统(全部独立)  │ │ 存储/监控层       │
│ embodied/ ✅    │ │ agent/ ✅ 131测试    │ │ data/ (json+db)  │
│  22 子包        │ │ vision/ ✅ 136测试   │ │ memory/ 长期记忆  │
│  service.py     │ │ action/ ✅ 151测试   │ │ human_feedback/  │
│  (唯一入口)     │ │ personality/✅137    │ │ logs/ (webui_*.   │
│  companion/     │ │ voice_identity/     │ │  log, backend.log │
│  主代理+宪法     │ │  ✅ 181测试         │ │  ⚠无轮转)        │
└────────────────┘ └──────────────────────┘ └────────────────────┘

✅=运行时已接线  ❌=仅测试/未接线(死代码)  ⚠=有缺陷(详见 §六)
```

---

## 三、端口总表

| 端口 | 服务 | 绑定 | 入口文件 | 启动方式 | 用途 |
|---|---|---|---|---|---|
| 5000 | WebUI | 127.0.0.1 | `webui_server.py` | `start.bat` / `python webui_server.py` | 页面+服务编排+API代理+SSE透传 |
| 8000 | 后端 API | 0.0.0.0 | `backend/main.py` | WebUI 内启动 / `python backend/main.py` | 全部业务 API + /ws |
| 8081 | Live2D 桌宠 | 127.0.0.1 | `live2d_qt_avatar.py` | WebUI 服务面板 | 桌宠形象（PyQt5+QOpenGL） |
| 8900 | 审计隔离实例 | 127.0.0.1 | 审计脚本 BOOT_CODE | 审计脚本自动 spawn | V10.1.9 审计专用 |

### 端口使用纪律
- 8000 被占用时 WebUI 直接"接管"（`is_port_in_use` 检测，webui_server.py:228-244）；
  接管后 pid 丢失、停止按钮失效、退出时被 `kill_port_process(8000)` 误杀（审计 GAP-1）
- 审计脚本固定 8900，运行前须确认空闲；禁止在 8000/5000 上做破坏性测试
- 端口硬编码（main.py uvicorn.run port=8000），无 env 化配置项

---

## 四、详细架构分层

### 4.1 前端层
| 组件 | 文件 | 职责 | 现状 |
|---|---|---|---|
| WebUI 服务编排 | `webui_server.py`（1465 行） | 启停 backend/live2d/voice_chat、API 代理（/api/* → :8000）、SSE 透传（/api/chat/stream）、启动日志 | ✅ 运行正常；接管后端生命周期不一致⚠ |
| 前端页面 | `webui_templates/index.html`（165KB） | SSE fetch 解析、sequence 单调校验、旧 turn 丢弃、streamPlayer 顺序播放、VAD 录音、服务卡片 | ✅ 正常；无断线重连⚠、状态面板仅 2/11 态⚠ |
| 静态资源 | `webui_static/` | JS/CSS/图标 | ✅ |
| 桌面壳 | `frontend/main.py` + runtime/startup/avatar/monitor/settings | 一键启动元亨、运行时状态机、情绪动画 | ✅ 118 测试；RuntimeConsole 死面板⚠ |
| 桌宠 | `live2d_qt_avatar.py`（备选 pygame） | Live2D 渲染、情绪动作 | ✅ |

### 4.2 对话运行时层（V10.1.7/1.8 核心）
| 模块 | 状态机/关键行为 | 现状 |
|---|---|---|
| `conversation_controller.py`（477 行） | 11 态状态机（IDLE→RECEIVING→READY→PROCESSING→STREAMING→TTS_PLAYING→COMPLETED→IDLE + INTERRUPTED/QUEUED/RECOVERY/ERROR）；事件协议（START/TOKEN/FLUSH/COMPLETE/INTERRUPTED/ERROR/HEARTBEAT）；RLock | ✅ 规范定义完整；生产只发 START/TOKEN/COMPLETE；mark_tts_playing/interrupt_turn/recover_turn 生产零调用⚠；非法迁移仅警告仍执行⚠；_turns 无上限⚠ |
| `context_manager.py`（661 行） | 8 条窗口（硬编码 MAX_HISTORY_MESSAGES=8）+ 工作摘要（5 字段保留）+ token 阈值 LLM 摘要（7000） | ✅ 功能正常；无锁⚠、双压缩机制竞争⚠、裁剪不对称⚠ |
| `input_aggregator.py`（287 行） | 分类(important/normal/chat/noise)/合并(重叠≥80%)/优先级队列(上限30) | ❌ **未接线**（仅测试） |
| `conversation_manager.py`（377 行，旧） | 旧对话状态机 IDLE/LISTENING/THINKING/SPEAKING/INTERRUPTED、50 条历史 | ⚠ 与 turn 控制器双历史并存；无 handle_ws（/ws 死端点） |

### 4.3 模型层
| 模块 | 职责 | 现状 |
|---|---|---|
| `llm_engine.py`（422 行） | LLM 单客户端（dashscope/deepseek）、generate_stream、离线降级文案、响应缓存(MD5,1000条,TTL300s) | ✅ 运行时接线；无读流超时⚠、无重试⚠、无 connect/disconnect 方法⚠（/modules/start llm 失效） |
| `model_pool/`（V10.1.3，Router/Registry/Selector/Handoff） | 主备模型切换、任务分类、交接上下文 | ❌ **未接线**；66 测试全过；latency 不回写 registry（切换条件永不满足）⚠ |
| `token_opt/`（V10.1.3） | ConversationCompressor/ResponseCache/TokenBudget | ❌ **未接线**；42 测试全过 |
| `memory_policy.py`（V10.1） | 显存仲裁（ASR 1.5GB/TTS 3.5GB 共存规则） | ❌ **未接线**；22 测试全过；无锁⚠ |

### 4.4 语音层
| 模块 | 职责 | 现状 |
|---|---|---|
| `tts_engine.py` + `tts/`（manager + qwen3_customvoice/qwen3/gpt_sovits/edge + adapters） | 回退链：qwen3-tts-customvoice → qwen3-tts → gpt-sovits → edge-tts；流式合成；情绪→音色映射 | ✅ 接线；**当前机器全链回退静音 mock**（faster_qwen3_tts/qwen_tts 模块缺失、gpt-sovits 加载异常、edge 声线 'Vivian' 无效）⚠ |
| `asr_engine.py`（1110 行） | FunASR SenseVoiceSmall → whisper 回退、多遍识别、音频增强、流式识别 | ✅ 接线；未加载时返回**编造文本**⚠；transcribe_file 方法缺失⚠（/voice/quality 失效）；30s 超时 |
| `vad_engine.py` | 纯能量检测状态机（energy_threshold=0.015、min_voiced_frames=2） | ✅ 接线；`main.py:1950` 调 `set_interrupted` 不存在 → 打断 HTTP 500（实证）⚠ |
| `audio_buffer.py`（309 行） | 播放缓冲、打断清空、自播窗口回声过滤、口型同步 | ✅ 接线；无界队列⚠、无锁⚠ |
| `echo_cancellation.py`（591 行） | AEC 算法（NLMS/频域/回声抑制） | ❌ **死代码**（全仓库零 import） |
| `noise_suppression.py` / `audio_enhancer.py` | 降噪/增强（被 asr 间接调用） | ✅ 间接接线 |

### 4.5 Agent 认知层
| 模块 | 内容 | 测试 |
|---|---|---|
| `embodied/` | service.py（唯一入口）+ companion/ 22 子包（personality~memory_stabilization~interaction）+ 治理（constitution 5 子目录）+ hybrid/audit + 环境/经验/规划/推理/策略/世界模型 | 8618 ✅ |
| `agent/` | ReAct/Planner/Tool/Plugin/LLM 双模式 | 131 ✅ |
| `vision/` | 屏幕/摄像头/Mock + perception（OCR/检测）+ understanding（VLM）+ memory | 136 ✅ |
| `action/` | 行动执行/规划/权限/治理 | 151 ✅ |
| `personality/` | 人格管理 | 137 ✅ |
| `voice_identity/` | 声音克隆/批量/审计/生命周期 | 181 ✅ |

### 4.6 存储与数据
```
backend/data/personality.json    人格配置（铁哥们）
backend/data/voice_identity.db   声音身份库
backend/data/vision_memories.db  视觉记忆
backend/data/agent_memories.db   Agent 记忆
memory/                          长期基础记忆（用户身份/项目上下文/协作规则）
human_feedback/                  每日反馈
logs/                            webui_YYYYMMDD.log / backend_stdout.log / stderr.log
backend.log（根目录）             后端主日志 ⚠单文件无轮转（实测 ~4.5KB/s 增长）
```

### 4.7 监控与观测
| 端点 | 内容 | 现状 |
|---|---|---|
| GET /health | 模块状态（status/llm/asr/tts/vad/provider/model） | ⚠ 恒 healthy，模块挂掉也 healthy（ASR 未加载实证） |
| GET /modules/status | asr/tts/vad/llm 四模块运行态 | ✅ 可用 |
| GET /cache-stats | llm 连接/上下文 token/audio buffer | ✅ 可用 |
| GET /metrics | Prometheus 文本（仅 voice 克隆指标） | ⚠ 无对话/LLM/进程指标 |
| GET /websocket-stats | WS 连接统计 | ✅ |
| GET /voice/dashboard | 声音系统仪表盘 | ✅ |

---

## 五、配置总表（.env + config.py 默认值）

加载机制：`config.py` 用 `load_dotenv(override=True)` 读项目根 `.env`（L13-15）；
`config = Config()` 全局单例（L396）；**未在 .env 设置的项目使用默认值**。
禁止重复定义同名配置项；测试模式前缀 `YHLZ_*_TEST_MODE`。

### 5.1 模型提供商（当前 .env 实值）

| 配置项 | 默认值 | .env 当前值 | 说明 |
|---|---|---|---|
| API_PROVIDER | dashscope | **dashscope** | 当前生效提供商 |
| DASHSCOPE_API_KEY | "" | 系统环境变量读取 | 阿里云密钥（.env 未写） |
| DASHSCOPE_MODEL | qwen-turbo | **qwen-turbo** | 当前 LLM 模型 |
| DEEPSEEK_API_KEY | "" | **已设置(脱敏)** | 备用提供商密钥 |
| DEEPSEEK_BASE_URL | https://api.deepseek.com | 默认 | |
| DEEPSEEK_MODEL | deepseek-chat | **deepseek-chat** | |
| VL_MODEL | qwen-vl-plus | 默认 | 视觉理解 |

### 5.2 ASR（asr_* 前缀）

| 配置项 | 默认值 | .env 当前 | 说明 |
|---|---|---|---|
| ASR_MODEL | funasr-SenseVoiceSmall | **funasr-SenseVoiceSmall** | 当前 ASR 模型 |
| ASR_DEVICE | cuda | **cuda** | GPU 推理 |
| USE_FP16 | true | **true** | bf16 精度 |
| USE_KV_CACHE | true | **true** | |
| ASR_FAST_MODE | true | **true** | |
| ASR_LANGUAGE | zh | 默认 | 中文识别 |
| ASR_MODE | accuracy | 默认 | 精度模式 |
| ASR_BEAM_SIZE / BEST_OF | 10 / 10 | 默认 | 束搜索 |
| ASR_PATIENCE | 2.0 | 默认 | |
| ASR_TEMPERATURE | 0.0,0.1,0.2 | 默认 | |
| ASR_NO_SPEECH_THRESHOLD | 0.4 | 默认 | 静音判定 |
| ASR_LOG_PROB_THRESHOLD | -0.5 | 默认 | 置信度 |
| ASR_COMPRESSION_RATIO_THRESHOLD | 2.4 | 默认 | 压缩比 |
| ASR_MULTI_PASS_ENABLED | true | 默认 | 多遍识别 |
| ASR_MULTI_PASS_CONFIDENCE_THRESHOLD | -0.3 | 默认 | |
| ASR_AUDIO_ENHANCEMENT_ENABLED | true | 默认 | 音频增强 |
| ASR_TEXT_POSTPROCESSING_ENABLED | true | 默认 | 文本后处理 |

### 5.3 TTS 与音频（tts_* / audio）

| 配置项 | 默认值 | .env 当前 | 说明 |
|---|---|---|---|
| TTS_ENGINE | qwen3-tts-customvoice | **qwen3-tts-customvoice** | 默认引擎（当前机器不可用→静音回退⚠） |
| TTS_MAX_CHUNK_LENGTH | 50 | **50** | 断句安全上限 |
| TTS_FIRST_CHUNK_MIN_MS | 300 | **300** | 首段就绪即开口 |
| TTS_FALLBACK_BUFFER_ENABLED | false | **false** | 2 秒保底缓冲（默认关） |
| TTS_BUFFER_MS | 10 | **10** | 缓冲粒度 |
| SAMPLE_RATE | 16000 | **16000** | 统一音频采样率 |
| EMOTION_ENABLED | false | 默认 | 情绪→音色映射 |
| EMOTION_CONFIDENCE_THRESHOLD | 0.5 | 默认 | |
| ECHO_FILTER_ENABLED | true | 默认 | 回声过滤 |

### 5.4 上下文 / 对话（硬编码项⚠）

| 配置项 | 默认值 | .env 当前 | 说明 |
|---|---|---|---|
| MAX_CONTEXT_TOKENS | 8000 | **8000** | token 计数阈值（不参与窗口截断） |
| SUMMARY_THRESHOLD | 7000 | **7000** | LLM 摘要触发阈值 |
| 上下文窗口 | — | — | ⚠ 硬编码 8 条（context_manager MAX_HISTORY_MESSAGES） |
| 队列上限 | — | — | ⚠ 硬编码 20（turn 队列）/ 30（aggregator） |
| LLM 读流超时/重试/SSE 心跳/打断策略 | — | — | ⚠ 全部无配置项 |

### 5.5 各子系统开关与阈值（默认值，未在 .env 设置的均用默认）

| 组 | 关键配置项（默认值） |
|---|---|
| Agent | agent_enabled(true)/max_iterations(5)/tool_timeout(10)/enable_memory(true)/short_term_size(20)/auto_extract(true) |
| Vision | vision_enabled(false)/screen(false)/camera(false)/capture_interval(1.0)/save_policy(memory)/max_frame 1920×1080 |
| Perception | perception_enabled(false)/ocr(false)/detection(false)/permission_required(true)/ocr_provider(mock)/detection_provider(mock)/min_confidence(0.0/0.5) |
| Understanding | understanding_enabled(false)/provider(mock)/timeout(30)/max_tokens(512)/vlm_base_url(dashscope 兼容端点) |
| Vision Memory | vision_memory_enabled(false)/default_importance(medium)/max_query_limit(100) |
| Personality | personality_enabled(false)/allow_sensitive(false)/max_profiles(50) |
| Action | action_enabled(false)/require_confirm_high_risk(true)/default_risk(low)/timeout(10)/history_max(200) |
| Embodied | embodied_enabled(false)/require_confirm_high_risk(true)/default_environment(mock)/state_history_max(100)/loop_max_iterations(5)/action_timeout(10) |
| Companion | companion_enabled(false)/agent_timeout(10)/route_rule_version(v1)/delegate_workers(4)/route_topk(3)/stats_max_records(500) |
| 人格/关系 | companion_personality_base(铁哥们)/adjust_step(0.1)/decay_enabled(true)/relationship_enabled(true)/statistics_window_days(30)/decay_rate(0.05) |
| 记忆/稳定化 | companion_memory_stabilize_enabled(true)/prune_value_threshold(0.3)/prune_age_days(90)/compress_similarity(0.9) |
| 治理/安全 | growth_auto_apply(**false** 硬保持)/identity_guard_enabled(true)/constitution_enabled(true)/ledger_max(5000) |
| 成长/情绪/节律 | companion_growth_enabled(true)/emotion_enabled(true)/decay_rate(0.05)/rhythm_enabled(true)/consolidate_threshold(20) |
| 混合智能 | companion_hybrid_enabled(true)/cloud_enabled(true)/high_cost_threshold(0.01)/low_value_threshold(0.3)/max_tokens(4096) |
| 研究/元认知/创造 | companion_research_enabled(true)/max_loops(3)/meta_cognition_enabled(true)/meta_creative_enabled(true) |
| 交互协议 | companion_interaction_enabled(true)/max_context_len(200)/max_pending(20)/max_flows(500)/latency_max_samples(1000) |

### 5.6 测试模式开关

| 环境变量 | 作用 |
|---|---|
| YHLZ_TEST_MODE | voice_identity 全局 Mock（setup_test_mode） |
| YHLZ_AGENT_TEST_MODE / YHLZ_VISION_TEST_MODE / YHLZ_PERCEPTION_TEST_MODE / YHLZ_PERSONALITY_TEST_MODE / YHLZ_ACTION_TEST_MODE / YHLZ_EMBODIED_TEST_MODE / YHLZ_UNDERSTANDING_TEST_MODE / YHLZ_VISION_MEMORY_TEST_MODE | 各子系统 Mock 模式 |

---

## 六、现状缺口（引用 V10.1.9 审计结论，详见审计报告）

| 级别 | 缺口 | 位置 |
|---|---|---|
| Critical | /chat 生成器异常 → turn 永久卡 STREAMING，无 ERROR 帧 | main.py:694-789 |
| Critical | claim_ready_turn() 返回值被忽略 → 队列失效，并发同时流式 | main.py:696 |
| Critical | 分层打断未接线：LLM 不取消/TTS 继续播放/无 INTERRUPTED 事件 | main.py:889-892 |
| Critical | LLM 流无超时无重试 → 上游挂起对话卡死 | llm_engine.py:222-253 |
| Critical | TTS 全链静音 mock（模块缺失+声线无效）→"播放无声"根因 | tts/ + edge.py |
| High | 3 处方法名硬 bug：set_interrupted / llm connect / transcribe_file / /ws handle_ws | main.py:1950,2468,2505,1355,3841 |
| High | InputAggregator / model_pool / token_opt / memory_policy 未接线 | 各模块 |
| High | ContextManager 无锁 + 双压缩竞争 + 裁剪不对称 | context_manager.py |
| High | 日志无轮转（backend.log ~4.5KB/s 增长）+ turn 无 JSONL + /health 恒真 | main.py + 日志 |
| Medium | ASR 未加载返回编造文本 / 前端无重连 / 状态面板 2/11 态 | asr_engine.py / index.html |

---

## 七、维护与变更记录

- 本文档由热机阶段工程文档体系维护；配置变更必须同步更新 §五
- 端口/接线状态变更必须同步 §二/§三，并在审计报告中留痕
- 白皮书数据可复现方式：`Get-Content .env`、`netstat -ano`、`venv\Scripts\python.exe -c "from backend.config import config; print(config)"`

### 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-08-12 | V10.1.9 | 初版：基于 config.py 全量 + .env 实读 + 端口实测 + V10.1.9 审计结论 |

---

**YHLZ · 元 · 亨 · 利 · 贞**

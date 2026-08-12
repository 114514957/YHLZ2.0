# YHLZ 端口与配置白皮书

> 版本：V10.1.5（热机阶段）
> 日期：2026-08-10
> 范围：全部服务端口 + 全部配置项（286 项）+ 环境变量
> 用途：热机运行/运维/排障参考

---

## 目录

1. [端口总览](#一端口总览)
2. [配置体系](#二配置体系)
3. [核心配置详解](#三核心配置详解)
4. [子系统配置](#四子系统配置)
5. [环境变量（.env）](#五环境变量env)
6. [配置文件位置](#六配置文件位置)
7. [端口与配置变更记录](#七端口与配置变更记录)

---

## 一、端口总览

### 1.1 服务端口

| 端口 | 服务 | 协议 | 绑定 | 说明 |
|---|---|---|---|---|
| **5000** | WebUI 控制台 | HTTP | 127.0.0.1 | `webui_server.py`，浏览器管理界面 |
| **8000** | Backend API | HTTP | 0.0.0.0 | `backend/main.py`，FastAPI 121 路由 |
| **8081** | Live2D 桌宠服务 | HTTP | — | `live2d_desktop_avatar.py` 服务模式 |
| **18765** | 桌宠内嵌 Live2D 查看器 | HTTP | — | 优先于 8081（`/live2d_viewer.html`） |

### 1.2 端口角色明细

| 端口 | 消费方 | 生产者 | 关键接口 |
|---|---|---|---|
| 5000 | 浏览器 | webui_server.py | `/api/status` `/api/health` `/api/chat` `/api/voice/*` 等 50+ 代理 |
| 8000 | WebUI 代理 / 前端壳 / 桌宠 | backend/main.py | `/chat` `/transcribe` `/synthesize` `/voice/*` `/live2d/*` `/memory/*` 等 121 路由 |
| 8081 | 浏览器 (查看器) | 桌宠内嵌 HTTP | `/live2d_viewer.html` |
| 18765 | 浏览器 (查看器) | 桌宠内嵌 HTTP | `/live2d_viewer.html`（优先） |

### 1.3 端口状态探测机制

```
WebUI /api/status 三态探测:
  - 端口服务 (backend 等): socket connect 探测 is_port_in_use()
  - 进程服务 (live2d/avatar): psutil Process.poll()
  - 线程内服务 (asr/tts): 布尔标志位

端口冲突处理: 启动前 is_port_in_use → kill_port_process (psutil terminate)
优雅关闭: /api/shutdown → avatar → live2d → backend → 释放 5000/8000/8081
```

### 1.4 代码内端口引用

| 文件 | 端口 |
|---|---|
| webui_server.py | 5000（主）、8000（代理）、8081（Live2D）、18765（查看器） |
| backend/main.py | 8000 |
| start.bat | 5000 |
| live2d_desktop_avatar.py | 8081 |
| live2d_qt_avatar.py / live2d_pygame_avatar.py | 8000（WS 后端连接） |
| frontend/startup/initializer.py | 8000（backend_url） |

---

## 二、配置体系

### 2.1 配置架构

```
.env 环境变量 (最高优先级, 启动时读取)
  ↓
backend/config.py (Config Pydantic 模型, 291 项配置, 环境变量 + 默认值)
  ↓
各模块消费 (按前缀分组)
```

**配置规则**：
- 全部配置集中在 `backend/config.py`（禁止散落硬编码）
- 按子系统前缀命名：`asr_*` / `tts_*` / `llm_*` / `vad_*` / `vision_*` / `perception_*` / `agent_*` / `embodied_*` / `companion_*`
- 禁止重复定义同名配置项
- 测试模式：`YHLZ_TEST_MODE` / `YHLZ_VOICE_IDENTITY_TEST_MODE` / `YHLZ_VISION_TEST_MODE` / `YHLZ_PERCEPTION_TEST_MODE`

### 2.2 配置分组统计（286 项）

| 前缀 | 数量 | 说明 |
|---|---|---|
| companion | 113 | 认知伙伴（人格/记忆/反思/成长/治理/创造/研究/元认知/稳定化/交互） |
| embodied | 45 | 具身智能（环境/规划/策略/任务/风险） |
| perception | 21 | 感知（OCR/检测/权限/适配器） |
| asr | 16 | 语音识别（模型/精度/增强） |
| vision | 16 | 视觉（采集/保存/权限） |
| understanding | 12 | 视觉理解（VLM/权限/超时） |
| agent | 8 | Agent Core（迭代/工具/记忆） |
| action | 7 | 行动（风险/确认/超时） |
| personality | 6 | 人格子系统（数据库/敏感/上限） |
| tts | 5 | 语音合成（引擎/分块/缓冲） |
| model | 5 | 模型抽象（provider/model/key） |
| 其他 | 32 | 记忆网关/成长/情感/回显/多模态等 |

---

## 三、核心配置详解

### 3.1 模型与 API（热机关键）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `api_provider` | dashscope | API 提供方（dashscope/deepseek） |
| `dashscope_model` | qwen-turbo | 主 LLM（百万 Token 额度） |
| `dashscope_api_key` | sk-0ee5... | DashScope 密钥（.env 注入） |
| `deepseek_model` | deepseek-chat | 备用 LLM |
| `deepseek_api_key` | sk-0ee5... | DeepSeek 密钥 |
| `deepseek_base_url` | https://api.deepseek.com | DeepSeek 端点 |
| `vl_model` | qwen-vl-plus | 视觉理解模型（DashScope） |
| `current_api_key` | sk-0ee5... | 当前生效密钥（按 provider） |
| `is_valid` | True | 配置有效性（有 API key） |

### 3.2 语音链路（热机关键）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `asr_model` | funasr-SenseVoiceSmall | ASR 模型（本地，懒加载） |
| `asr_device` | cuda | ASR 计算设备 |
| `asr_mode` | accuracy | 识别精度模式 |
| `asr_language` | zh | 识别语言 |
| `asr_fast_mode` | True | 快速模式 |
| `asr_audio_enhancement_enabled` | True | 音频增强（谱减+归一化） |
| `asr_multi_pass_enabled` | True | 多 pass 重识别 |
| `asr_beam_size` / `asr_best_of` | 10 / 10 | 束搜索参数 |
| `asr_no_speech_threshold` | 0.4 | 无语音判定 |
| `tts_engine` | qwen3-tts-customvoice | TTS 引擎（本地克隆版） |
| `tts_max_chunk_length` | 50 | 分块上限（字符） |
| `tts_first_chunk_min_ms` | 300 | 首块最小延迟 |
| `tts_buffer_ms` | 10 | 缓冲时长 |
| `sample_rate` | 16000 | 音频采样率 |
| `echo_filter_enabled` | True | 回声过滤 |
| `emotion_enabled` | False | 情绪→音色映射（当前关） |
| `emotion_confidence_threshold` | 0.5 | 情绪置信阈值 |

### 3.3 上下文与 Token

| 配置 | 当前值 | 说明 |
|---|---|---|
| `max_context_tokens` | 8000 | 上下文 Token 上限 |
| `summary_threshold` | 7000 | 摘要触发阈值 |
| `use_fp16` | True | FP16 精度 |
| `use_kv_cache` | True | KV 缓存 |

### 3.4 记忆与稳定化（V10.1）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `memory_gate_enabled` | True | 记忆网关 |
| `memory_gate_approve_threshold` | 0.6 | 批准阈值 |
| `memory_gate_reject_threshold` | 0.3 | 拒绝阈值 |
| `companion_memory_stabilize_enabled` | True | 记忆稳定化 |
| `companion_memory_stabilize_compress_similarity` | 0.9 | 压缩相似度阈值 |
| `companion_memory_stabilize_prune_value_threshold` | 0.3 | 淘汰价值阈值 |
| `companion_memory_stabilize_prune_age_days` | 90 | 淘汰超龄天数 |
| `companion_experience_max_records` | 200 | 经历存储上限 |

### 3.5 交互协议（V10.1）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `companion_interaction_enabled` | True | 交互协议层 |
| `companion_interaction_max_context_len` | 200 | 会话上下文上限 |
| `companion_interaction_max_pending` | 20 | 未完成事项上限 |
| `companion_interaction_max_flows` | 500 | 工具流程上限 |
| `companion_interaction_audit_max` | 2000 | 交互审计上限 |

### 3.6 治理与安全（热机冻结核心）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `companion_constitution_enabled` | True | 宪法引擎 |
| `companion_constitution_ledger_max` | 5000 | 总账上限 |
| `identity_guard_enabled` | True | 身份守护 |
| `growth_auto_apply` | False | **成长自动应用（硬保持 false）** |
| `growth_proposal_enabled` | True | 成长提案 |
| `companion_personality_base` | 铁哥们 | 核心人格（冻结） |
| `companion_persistence_enabled` | False | 持久化（需显式开启） |

### 3.7 权限（默认拒绝）

| 配置 | 当前值 | 说明 |
|---|---|---|
| `perception_enabled` | False | 感知（默认关） |
| `perception_permission_required` | True | 感知需权限 |
| `camera_access_enabled` | False | 摄像头（默认关） |
| `vision_enabled` | False | 视觉（默认关） |
| `ocr_enabled` | False | OCR（默认关） |
| `detection_enabled` | False | 检测（默认关） |
| `action_enabled` | False | 行动（默认关） |
| `personality_enabled` | False | 人格子系统（默认关） |
| `understanding_enabled` | False | 理解（默认关） |
| `tesseract_enabled` | False | Tesseract（默认关） |

---

## 四、子系统配置

### 4.1 Agent（8 项）

```
agent_enabled=True | agent_max_iterations=5 | agent_tool_timeout=10.0
agent_enable_memory=True | agent_short_term_size=20
agent_memory_db=backend/data/agent_memories.db | agent_test_mode=False
```

### 4.2 感知（21 项）

```
perception_default_ocr=ocr_mock | perception_default_detection=detection_mock
perception_detection_model=yolov8n.pt | perception_detection_device=cpu
perception_min_confidence=0.5 | perception_max_image_size=1920
perception_ocr_language=ch | perception_template_match_threshold=0.7
```

### 4.3 人格子系统（6 项）

```
personality_db_path=backend/data/personality_profiles.db
personality_max_profiles=50 | personality_allow_sensitive=False
```

### 4.4 视觉记忆（11 项）

```
vision_memory_db_path=backend/data/vision_memories.db
vision_memory_default_importance=medium | vision_memory_max_query_limit=100
```

### 4.5 认知伙伴（113 项，关键子集）

```
人格:     companion_personality_base=铁哥们 / adjust_step=0.1 / decay_rate=0.05
关系:     companion_relationship_enabled=True / statistics_window_days=30
记忆:     companion_experience_enabled=True / max_records=200 / archive_days=30
反思:     companion_verification_confirm_threshold=2 / pattern_min_occurrences=3
创造:     companion_creative_enabled=True / value_threshold=0.6
成长:     companion_growth_enabled=True / cycle_days=1 / auto_apply=False(冻结)
治理:     companion_constitution_enabled=True / ledger_max=5000
研究:     companion_research_enabled=True / max_loops=3
元认知:   companion_meta_cognition_enabled=True / memory_max=1000
情绪:     companion_emotion_enabled=True / decay_rate=0.05 / floor=0.1
节律:     companion_rhythm_enabled=True / consolidate_days=7
表达:     companion_expression_enabled=True / threshold=0.7
混合:     companion_hybrid_enabled=True / max_tokens=4096
存在:     companion_presence_enabled=True / intensity_step=0.15
```

### 4.6 具身（45 项，关键子集）

```
embodied_default_environment=mock | embodied_enabled=False(测试时开)
embodied_loop_max_iterations=5 | embodied_action_timeout=10.0
embodied_require_confirm_high_risk=True
embodied_planning_priority_weight_high=2.0 / medium=1.5 / low=1.0
embodied_rank_hit_rate_weight=0.5 / acceptance_weight=0.3 / recency_weight=0.2
embodied_risk_failure_threshold=3 / blocked_threshold=2
embodied_mission_max_phases=10 / retry_limit=2 / resume_enabled=True
```

---

## 五、环境变量（.env）

### 5.1 已配置（17 项）

| 变量 | 值 | 说明 |
|---|---|---|
| `API_PROVIDER` | dashscope | 提供方 |
| `DASHSCOPE_MODEL` | qwen-turbo | 主模型 |
| `DEEPSEEK_MODEL` | deepseek-chat | 备用模型 |
| `DEEPSEEK_BASE_URL` | https://api.deepseek.com | DeepSeek 端点 |
| `DEEPSEEK_API_KEY` | sk-***（脱敏） | DeepSeek 密钥 |
| `ASR_MODEL` | funasr-SenseVoiceSmall | ASR 模型 |
| `ASR_DEVICE` | cuda | ASR 设备 |
| `USE_FP16` | true | FP16 |
| `USE_KV_CACHE` | true | KV 缓存 |
| `ASR_FAST_MODE` | true | 快速模式 |
| `TTS_ENGINE` | qwen3-tts-customvoice | TTS 引擎 |
| `TTS_MAX_CHUNK_LENGTH` | 50 | 分块上限 |
| `MAX_CONTEXT_TOKENS` | 8000 | 上下文上限 |
| `SUMMARY_THRESHOLD` | 7000 | 摘要阈值 |
| `TTS_BUFFER_MS` | 10 | 缓冲 |
| `SAMPLE_RATE` | 16000 | 采样率 |
| `TTS_FIRST_CHUNK_MIN_MS` | 300 | 首块延迟 |

### 5.2 运行环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEBUI_PORT` | 5000 | WebUI 端口 |
| `WEBUI_HOST` | 127.0.0.1 | WebUI 绑定 |
| `WEBUI_AUTO_OPEN` | true | 自动开浏览器 |
| `YHLZ_TEST_MODE` | — | 测试模式 |
| `YHLZ_RUN_REAL_TESTS` | — | 真实设备测试 |

---

## 六、配置文件位置

| 文件 | 用途 | 修改方式 |
|---|---|---|
| `D:\YHLZ2.0\.env` | 环境变量（密钥/模型） | 手动编辑 |
| `D:\YHLZ2.0\backend\config.py` | 全部配置定义（291 项） | 代码级（冻结） |
| `D:\YHLZ2.0\backend\data\personality.json` | 人格配置（铁哥们） | 手动/API |
| `D:\YHLZ2.0\backend\data\voice_identity.db` | 声音身份数据库 | API |
| `D:\YHLZ2.0\backend\data\vision_memories.db` | 视觉记忆数据库 | API |
| `D:\YHLZ2.0\backend\data\agent_memories.db` | Agent 记忆 | API |
| `D:\YHLZ2.0\memory\user_identity.md` | 用户身份锚点 | 用户手动（冻结） |
| `D:\YHLZ2.0\memory\yhlz_project_context.md` | 项目上下文 | 用户确认后 |
| `D:\YHLZ2.0\memory\collaboration_rules.md` | 协作规则 | 用户手动 |
| `D:\YHLZ2.0\webui_config.json` | WebUI 设置 | WebUI /api/config/save |
| `D:\YHLZ2.0\gui_config.json` | GUI 状态 | GUI |
| `D:\YHLZ2.0\frontend_settings.json` | 前端壳设置 | 设置面板 |
| `D:\YHLZ2.0\human_feedback\` | 每日反馈 | HumanOperatorLayer |

---

## 七、端口与配置变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 08-10 | `/api/health` 状态归一化（healthy→ok） | UI 误报修复（未改端口/配置） |
| 08-10 | `/api/chat` SSE 透传 | 兼容后端流式（未改端口/配置） |
| 08-10 | 前端增益 INPUT_GAIN=8 + 阈值 0.002（index.html） | 麦克风声音偏小 |
| 08-10 | 前端 MediaRecorder start(1000) 分片 | 语音对话无数据产出 |
| 历史 | 端口 5000/8000/8081/18765 固定 | 架构冻结 |

**热机冻结**：端口与核心配置（模型/API/治理）冻结，仅允许 WebUI 前端层适配性修改（如本次增益/分片修复）。

---

**YHLZ · 元 · 亨 · 利 · 贞**

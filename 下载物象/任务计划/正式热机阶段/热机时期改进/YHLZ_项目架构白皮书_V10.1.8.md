# YHLZ 项目详细架构白皮书

> 版本：V10.1.8（Real-time AI Companion Runtime）
> 日期：2026-08-10
> 状态：全量 9472 tests Failed=0
> 定位：YHLZ AI伙伴「元亨」完整架构说明

---

## 目录

1. [系统总览](#一系统总览)
2. [分层架构](#二分层架构)
3. [对话运行时架构](#三对话运行时架构)
4. [认知伙伴架构（Embodied）](#四认知伙伴架构embodied)
5. [声音身份架构](#五声音身份架构)
6. [多模态与感知架构](#六多模态与感知架构)
7. [模型抽象与调度架构](#七模型抽象与调度架构)
8. [Token 优化与记忆治理架构](#八token-优化与记忆治理架构)
9. [前端架构](#九前端架构)
10. [数据流详解](#十数据流详解)
11. [模块依赖关系](#十一模块依赖关系)
12. [部署与运维架构](#十二部署与运维架构)

---

## 一、系统总览

### 1.1 三层结构

```
┌──────────────────────────────────────────────────────────────┐
│ 表现层 (用户交互)                                              │
│  ├─ WebUI 控制台 (webui_server.py :5000, 21 功能页)            │
│  ├─ 桌面伙伴壳 (frontend/main.py, 一键启动元亨)                │
│  └─ Live2D 桌宠 (live2d_desktop_avatar.py :8081/18765)        │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP :5000 (代理)
┌──────────────────────────▼───────────────────────────────────┐
│ 对话系统层 (backend 根目录, :8000)                             │
│  ├─ 对话控制: conversation_controller.py + input_aggregator.py│
│  ├─ 上下文:   context_manager.py                              │
│  ├─ 语音链路: asr_engine / tts / vad_engine / audio_buffer    │
│  ├─ 音频增强: audio_enhancer / echo_cancellation              │
│  │           / noise_suppression                              │
│  ├─ 治理层:   model_pool / token_opt / human_io               │
│  └─ API:      main.py (FastAPI, 121+ 路由)                    │
└──────────────────────────┬───────────────────────────────────┘
                           │ 内部调用 (同进程/跨进程)
┌──────────────────────────▼───────────────────────────────────┐
│ 认知伙伴层 (backend/embodied, 认知引擎)                        │
│  ├─ service.py (EmbodiedService 唯一 API)                     │
│  ├─ companion/ (22 子包: 人格/记忆/反思/成长/治理/创造/研究     │
│  │             /元认知/稳定化/交互/健康指标)                    │
│  └─ environment/planning/reasoning/strategy/world_model       │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 子系统清单（独立测试单元）

| 子系统 | 位置 | 测试数 | 职责 |
|---|---|---|---|
| Embodied | backend/embodied | 8618 | 认知伙伴引擎 |
| Vision | backend/vision | 136 | 视觉感知 |
| Action | backend/action | 151 | 行动执行 |
| Agent | backend/agent | 131 | Agent Core |
| Personality | backend/personality | 137 | 人格管理 |
| Voice Identity | backend/voice_identity | 181 | 声音身份 |
| Frontend | frontend | 118 | 桌面伙伴壳 |
| **TOTAL** | | **9472** | |

---

## 二、分层架构

### 2.1 铁律

```
Interface → Service → Manager → Storage / Adapter
```

| 层 | 职责 | 约束 |
|---|---|---|
| Interface | API 定义 | 冻结（只允许新增字段/新 API 独立命名） |
| Service | 业务逻辑（唯一 API 入口） | 跨子系统协作只能经 Service 层 |
| Manager | 引擎聚合/生命周期 | 不直接暴露外部 |
| Storage/Adapter | 存储与外部能力 | Adapter 不调 Service |

### 2.2 模块独立性

```
backend/voice_identity/ 不依赖 backend/agent/
backend/agent/ 不依赖 backend/voice_identity/
backend/vision/ 独立
backend/embodied/ 独立 (认知层)
backend/model_pool/ token_opt/ human_io/ 独立 (治理层)
frontend/ 独立 (表现层)
跨子系统协作: 仅经 Tool System 或 Service 层 API
```

---

## 三、对话运行时架构

### 3.1 对话控制链（V10.1.7/8）

```
用户输入
  ↓
Input Aggregator (V10.1.8: 分类/合并/优先级治理)
  ↓
Turn Controller (V10.1.7: 状态机/事件/队列/打断)
  ↓
Context Manager (8条窗口 + 工作摘要压缩)
  ↓
LLM Streaming (qwen-turbo)
  ↓
事件协议 SSE (START/TOKEN/COMPLETE)
  ↓
WebUI Renderer (sequence 防乱序)
  ↓
句级切分 → 并行 TTS → 顺序播放 (DEMO 流模式)
```

### 3.2 状态机（11 态）

```
IDLE → RECEIVING → READY → PROCESSING → STREAMING
  → TTS_PLAYING → COMPLETED → IDLE
异常: PROCESSING/STREAMING/TTS_PLAYING → INTERRUPTED
      → QUEUED / READY
      ERROR → RECOVERY → READY
```

### 3.3 事件协议

```
事件: START / TOKEN / FLUSH / COMPLETE / INTERRUPTED / ERROR / HEARTBEAT
字段: conversation_id / turn_id / timestamp / sequence / event_type / payload
前端: sequence 单调递增, 旧 turn 事件丢弃
```

### 3.4 关键组件

| 组件 | 文件 | 职责 |
|---|---|---|
| Turn Controller | conversation_controller.py | 状态机/事件/队列(20)/打断/延迟追踪 |
| Input Aggregator | input_aggregator.py | 分类(4类)/重复合并(80%)/优先级队列 |
| Context Manager | context_manager.py | 8条窗口 + 工作摘要(5类信息) |
| 分层打断 | conversation_controller.py | llm取消/tts停止(最高)/queue清理 |
| 延迟追踪 | 内建 | input_start→turn_close 11 阶段 |

---

## 四、认知伙伴架构（Embodied）

### 4.1 门面

```
EmbodiedService (service.py, 唯一 API 入口)
  └─ 170+ companion_* API
  └─ MainCompanionAgent (main_agent.py, 引擎聚合/路由/委派)
```

### 4.2 companion/ 22 子包

| 子包 | 版本 | 职责 |
|---|---|---|
| personality | V5.5/5.6 | 人格/关系/衰减 |
| experience | V5.7 | 经历记忆 |
| reflection | V5.8/6.5/6.6 | 反思/模式/矛盾/改进 |
| verification | V5.8 | 验证/证据/置信/现实检查 |
| creative | V5.9 | 创造/机会/提案/模拟 |
| continuity | V6.0 | 连续/快照/恢复 |
| persistence | V6.0 | 持久化 |
| identity_history | V6.0 | 身份历史 |
| emotion | V6.1.1 | 情绪状态/衰减 |
| rhythm | V6.1.1 | 节律/合并调度 |
| expression | V6.2 | 表达 |
| perception | V6.2~6.4 | 感知/记忆网关/管道 |
| memory | V6.3 | 记忆索引/重要度/合并 |
| identity | V6.5 | 身份守护 |
| growth | V6.5/6.6 | 成长/趋势/循环 |
| hybrid | V6.8 | 混合智能(本地/云端) |
| embodied_presence | V7.0 | 具身存在 |
| constitution | V8.0 | 宪法(原则/身份/安全/成长/智能) |
| creative_intelligence | V8.5 | 元创造力 |
| research_engine | V9.0 | 自主研究 |
| meta_cognition | V9.5 | 元认知 |
| memory_stabilization | V10.1 | 记忆稳定化 |
| interaction | V10.1 | 交互协议 |
| warm_health | V10.0 | 热机健康指标 |

### 4.3 治理优先级

```
Identity > Safety > Constitution > Cognition > Optimization
```

---

## 五、声音身份架构

```
backend/voice_identity/ (17 py)
  service.py (API) → manager.py (生命周期)
    ├─ registry.py (注册表)
    ├─ profile.py (音色档案)
    ├─ database.py (SQLite 持久化)
    ├─ cache_manager.py (缓存)
    ├─ dedup.py (去重)
    ├─ quality_gate.py (质量门禁)
    ├─ voice_lifecycle.py (生命周期)
    ├─ voice_security.py (安全)
    ├─ metrics.py / audit.py (指标/审计)
    └─ mock_loader.py (Mock)
```

流程：上传音频 → 质量门禁 → 去重 → 注册 → 克隆 → 缓存 → 使用

---

## 六、多模态与感知架构

### 6.1 感知（backend/vision）

```
vision/ (7 py)
  service.py → manager.py → interface.py
    ├─ adapters/ (屏幕/摄像头/Mock)
    ├─ perception/ (OCR/检测)
    ├─ understanding/ (VLM: qwen-vl-plus)
    └─ memory/ (视觉记忆)
```

### 6.2 人类/多模态输入（backend/human_io, V10.1.2）

```
HumanOperatorLayer: 任务/反馈/体验/问题/想法 + 每日反馈
MultimodalExperienceLayer: camera/screen/audio/video/danmaku
  → 价值评分 (0-10) → 0-4丢弃/5-7短期/8-10长期候选
  → 弹幕噪声过滤
```

---

## 七、模型抽象与调度架构

### 7.1 模型抽象

```
YHLZ Core → Model Router → Local / Cloud / Specialized Model
外部能力: Adapter 注册表 (TTS/LLM/Vision/Perception/ModelEndpoint)
HIL 网关: ApiGateway + ModelEndpoint.handler
```

### 7.2 模型池（backend/model_pool, V10.1.3）

```
ModelRegistry (10 字段登记) → TaskClassifier (8 类)
  → ModelSelector (评分: 能力0.4+上下文+Token+成本+延迟)
  → Token 状态 (GREEN/YELLOW/RED)
  → ModelHandoff (交接协议: 用户/项目/任务/结论/约束/下一步)
  → Fallback Mode (全不可用 → 本地)

默认池 (各百万 Token):
  qwen-turbo (main) / qwen-plus (specialist)
  qwen-vl-plus (specialist/vision) / deepseek-chat (specialist)
  local-fallback (local)
```

### 7.3 Token 优化（backend/token_opt, V10.1.3）

```
ConversationCompressor (10:1 压缩) → ResponseCache (LRU)
  → TokenBudget (日/月/应急, GREEN/YELLOW/RED)
  → TokenOptimizer (效率指标/价值率)
```

---

## 八、Token 优化与记忆治理架构

### 8.1 记忆治理（V10.1）

```
记忆稳定化 (memory_stabilization/):
  Compressor (同触发/同内容合并)
  Pruner (低价值+超龄+未确认 → 候选 → 显式执行)
  Weighter (频率/确认/引用动态权重)
  ConflictDetector (同主题正反结论)
  StabilizationAudit (全记录)
健康联动: WarmRuntimeHealth Memory 维度
```

### 8.2 记忆分层（V10.1.8）

```
短期窗口 (8条原始消息)
  ↓ 超窗压缩
工作摘要 (目标/任务/结论/未完成/实体)
  ↓ 按需检索
相关记忆
  ↓
长期记忆 (经历存储, CONFIRMED 才进长期参考)
```

---

## 九、前端架构

### 9.1 WebUI（webui_server.py :5000, 64KB）

```
服务编排 (启停/监控/崩溃恢复/端口管理)
API 代理 (50+ 路由 → :8000)
SSE 透传 (/api/chat/stream)
健康归一化 (/api/health healthy→ok)
前端页面 (index.html 21 功能页, ~3400 行)
```

### 9.2 桌面壳（frontend/, 17 py）

```
frontend/
  main.py         桌面主窗口 (一键启动元亨)
  avatar/         情绪驱动动画 (EmotionStateManager)
  runtime/        状态机/事件总线/追踪
  startup/        9步一键启动 (StartupCore)
  settings/       四组设置
  monitor/        开发模式控制台 (Ctrl+Shift+R)
```

### 9.3 语音对话前端（index.html 内）

```
vadRecorder:      能量VAD状态机 (说完识别)
streamPlayer:     并行TTS预合成 + 顺序播放
voiceInputQueue:  FIFO 输入队列
splitText:        句级切分 (4/8/50字)
isEcho:           防回声 (重叠率60%)
AudioContext:     用户手势创建 + AEC/NS/AGC
```

---

## 十、数据流详解

### 10.1 文本对话流

```
用户 → Input Aggregator → Turn Controller (READY)
  → Context (8条+摘要) → LLM Streaming
  → SSE 事件 (START/TOKEN/COMPLETE)
  → WebUI 渲染 (sequence 校验)
  → (可选) 句级切分 → 并行TTS → 顺序播放
```

### 10.2 语音对话流

```
麦克风 → VAD (0.015阈值/2帧确认/6帧尾音)
  → 语音段 (纯语音帧+1s预滚动) → 重采样16k+增益
  → ASR → 防回声 → 输入队列 → 对话流
```

### 10.3 声音克隆流

```
上传音频 → /voice/clone → 质量门禁 → 去重 → 注册 → 缓存
```

### 10.4 记忆流

```
事件 → 经历存储 → 验证(CONFIRMED) → 记忆分层
  → 稳定化 (压缩/淘汰/权重/冲突) → 健康指标联动
```

---

## 十一、模块依赖关系

### 11.1 依赖矩阵（核心）

```
webui_server.py ──HTTP──→ backend/main.py
backend/main.py ──依赖──→ context_manager / conversation_controller
                         / input_aggregator / asr_engine / tts_engine
                         / vad_engine / audio_enhancer / audio_buffer
                         / llm_engine
backend/main.py ──可选──→ model_pool / token_opt / human_io (治理层)
backend/main.py ──API───→ EmbodiedService (认知层, 按需)
frontend/ ──HTTP──→ backend (启动检查) / WebUI (代理)
```

### 11.2 独立子系统（互不依赖）

```
backend/agent/ ─ 独立
backend/vision/ ─ 独立
backend/action/ ─ 独立
backend/personality/ ─ 独立
backend/voice_identity/ ─ 独立
backend/embodied/ ─ 独立 (认知层)
backend/model_pool/ token_opt/ human_io/ ─ 独立 (治理层)
```

---

## 十二、部署与运维架构

### 12.1 端口

| 端口 | 服务 | 说明 |
|---|---|---|
| 5000 | WebUI | 控制台 |
| 8000 | Backend API | 业务核心 |
| 8081 | Live2D | 桌宠服务 |
| 18765 | 桌宠查看器 | 优先 |

### 12.2 启动链

```
start.bat → webui_server (:5000) → 浏览器
  → /api/services/backend/start → backend/main.py (:8000)
  → StartupCore 9步 → 元亨 ONLINE
```

### 12.3 运维

```
状态: /api/status (端口/进程/标志三态探测)
崩溃恢复: wait_backend 自动重启 (≤3次)
关闭: /api/shutdown (顺序停止+释放端口)
日志: logs/webui_YYYYMMDD.log + backend_stdout/stderr.log
数据: backend/data/*.db + memory/*.md + human_feedback/
```

### 12.4 配置

```
.env (密钥/模型) → backend/config.py (291项) → 各模块
前缀: asr_*/tts_*/llm_*/vad_*/vision_*/perception_*/agent_*
      /embodied_*/companion_*/interaction_*
模型: qwen-turbo / qwen-vl-plus / deepseek-chat
      / funasr-SenseVoiceSmall / Qwen3-TTS-0.6B
```

---

## 附：文件规模一览

```
后端主入口   main.py 152KB | webui_server.py 64KB | config.py 41KB
语音链路     asr_engine.py 45KB | text_postprocessor.py 43KB
             audio_enhancer.py 21KB | echo_cancellation.py 18KB
             noise_suppression.py 13KB | audio_buffer.py 10KB
对话控制     context_manager.py 26KB | conversation_controller.py 17KB
             input_aggregator.py 9KB | vad_engine.py 9KB
认知层       backend/embodied (service.py ~4200行 + companion 22子包)
治理层       model_pool(5) / token_opt(4) / human_io(3)
前端壳       frontend (17 py) | WebUI index.html ~3400行
DEMO 参考    voice_chat_demo.py 47KB (流模式基准)
```

---

**YHLZ · 元 · 亨 · 利 · 贞**

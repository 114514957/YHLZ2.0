# YHLZ 项目对话规则 · 架构 · 流式设计

> 版本：V10.1.7（热机时期总改进）
> 日期：2026-08-10
> 状态：READY（Stable Conversation Runtime 已建立）
> 依据：V10.1.7 热机时期总改进工程 Prompt + DEMO 流模式 + V10.1.5 全链路验证

---

## 目录

1. [对话规则总览](#一对话规则总览)
2. [架构设计](#二架构设计)
3. [流式设计](#三流式设计)
4. [对话生命周期状态机](#四对话生命周期状态机)
5. [事件协议](#五事件协议)
6. [数据流详解](#六数据流详解)
7. [数值配置总表](#七数值配置总表)
8. [可观察性与日志](#八可观察性与日志)
9. [验收标准](#九验收标准)

---

## 一、对话规则总览

### 1.1 核心原则

```
稳定性 > 对话体验 > 可观察性 > 可维护性 > 性能优化 > 高级能力扩展
```

- 任何新功能降低基础对话稳定性 → 暂缓
- 禁止推倒现有 Streaming（作为底层传输保留）
- 每个状态有明确进入/退出条件，可记录/可恢复/可诊断
- 禁止隐式状态

### 1.2 对话存储规则（3 句滑动窗口）

```
规则: 最多保留最近 3 条消息 (MAX_HISTORY_MESSAGES = 3)
实现: add_message 时超出 3 条 → 丢弃最旧
效果: 对话存储满 3 句后, 只输出这 3 句
      其他输入仍被接收进链路 (识别/入队), 但上下文自动滑出旧句
LLM 上下文: system(人格) + 最近 3 条对话
```

### 1.3 上下文优先级

```
Current Conversation (当前对话)
  > Working Context (工作上下文)
  > Relevant Memory (相关记忆)
  > Long-term Memory (长期记忆)

普通短聊: 不加载大量 Memory
复杂项目: 按需加载相关 Context
禁止: 每轮自动拼接全部身份/项目历史/Memory
```

### 1.4 输入接收规则

```
支持: 正常提交 / 连续输入 / 快速连续输入
      / 当前回答期间输入 / 打断当前回答 / 排队后续输入

文本聊天: 发送按钮/Enter 作为 Turn Boundary (明确提交优先)
语音对话: VAD 说完自动识别 (辅助机制)
自动等待窗口: 仅辅助, 不替代明确提交
所有阈值: 配置化、可测试、可回退 (禁止经验硬编码)
```

### 1.5 用户打断规则（Barge-in）

```
用户在 PROCESSING / STREAMING 时产生新输入:
  1. 创建新的 turn_id
  2. 取消旧生成 (INTERRUPTED)
  3. 停止继续向前端输出旧内容
  4. 保存必要的中断状态 (已输出文本保留)
  5. 新输入进入 READY
  6. 重新处理

禁止: 旧回答继续输出到新问题之后 / 新输入静默丢失 / 上下文污染
参考: DEMO generation token 对比机制
```

### 1.6 连续输入排队

```
队列要求: 有序 / 可追踪 / 不丢失 / 有上限(20) / 超限明确错误
每条消息: turn_id / timestamp / state / source / content_hash
前端语音输入队列: FIFO, 每句只输出一遍
```

### 1.7 防回声规则

```
重叠率 > 60% (ECHO_OVERLAP_RATIO) 且文本 > 4 字 → 判回声 → 丢弃
目的: 防止 ASR 识别到 AI 播放声音形成死循环
```

---

## 二、架构设计

### 2.1 总架构

```
┌────────────────────────────────────────────────────────────┐
│ WebUI (浏览器)                                               │
│  ├─ Input Receiver (输入接收: 文本/语音VAD)                  │
│  ├─ Turn Controller Client (事件渲染/打断/队列)              │
│  ├─ Stream Renderer (SSE 事件渲染, sequence 防乱序)          │
│  ├─ DEMO 流播放器 (句级切分/并行TTS/顺序播放)                │
│  └─ 状态显示 (Conversation/LLM/Memory)                       │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP :5000 (webui_server 代理)
┌──────────────────────────▼─────────────────────────────────┐
│ API Gateway (webui_server.py)                               │
│  ├─ 服务编排 (启停/监控/崩溃恢复)                            │
│  ├─ API 代理 (50+ 路由 → :8000)                             │
│  ├─ /api/health 归一化                                      │
│  └─ /api/chat/stream SSE 透传                               │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP :8000
┌──────────────────────────▼─────────────────────────────────┐
│ Backend (FastAPI)                                           │
│  ├─ Conversation Turn Controller (对话控制层)               │
│  │    ├─ 状态机 (9 态)                                      │
│  │    ├─ 事件协议 (7 事件)                                  │
│  │    ├─ 队列 (20 上限)                                     │
│  │    ├─ 打断 (INTERRUPTED)                                 │
│  │    └─ 延迟追踪 (input→close 全阶段)                      │
│  ├─ Context Manager (3 句滑动窗口)                          │
│  ├─ Memory Layer (按需检索)                                 │
│  ├─ Model Router (模型池调度)                               │
│  └─ LLM Streaming (输出传输层)                              │
└────────────────────────────────────────────────────────────┘
```

### 2.2 分层边界

```
Conversation Control (对话控制层):
  接收 / Turn / 打断 / 排队 / 输出节奏 / 状态

Runtime (运行时层):
  上下文 / 能力调用 / Memory / Model Router / Agent能力

LLM (模型层):
  理解 / 推理 / 生成

不要把系统行为规则全部塞进 Prompt。
Turn Controller 不替代 Streaming (Streaming 是输出传输层)。
```

### 2.3 模块清单

| 层 | 模块 | 职责 |
|---|---|---|
| 前端 | `index.html` 语音对话区 | VAD 采音/事件渲染/流播放/打断/队列 |
| 前端 | `streamPlayer` | 句级并行 TTS 预合成 + 顺序播放 |
| 前端 | `vadRecorder` | 能量 VAD 状态机（说完识别） |
| 后端 | `conversation_controller.py` | Turn 状态机/事件/队列/打断/延迟 |
| 后端 | `context_manager.py` | 3 句滑动窗口上下文 |
| 后端 | `main.py /chat` | 事件协议 SSE 输出 |
| 网关 | `webui_server.py` | 服务编排 + API 代理 + SSE 透传 |

---

## 三、流式设计

### 3.1 流式传输（保留）

```
LLM Streaming → SSE → WebUI
禁止等待完整 Response 后一次性返回
```

### 3.2 Stream Flush 规则

```
禁止: 每个 token 单独刷新前端
禁止: 长时间积累后一次性输出
采用: 短文本缓冲 + 时间窗口 + 语义分段

DEMO 依据:
  - 首片尽快发送
  - 后续短周期 flush
  - 句级切分 (标点断句)
  - 避免句间明显卡顿
```

### 3.3 句级切分（splitTextForStreaming）

```
规则:
  句号/问号/感叹号/分号/省略号 (。！？；!?;…) → 断句 (≥4字)
  逗号/顿号 (，、,) → 断句 (≥8字)
  50 字无标点 → 强制断句
```

### 3.4 并行预合成 + 顺序播放（DEMO 流模式）

```
并行: 每句独立 TTS 请求 (不等上句播完)
顺序: seq 递增, 只有 next 就绪才播 (dispatcher)
失败: 失败哨兵, 不卡播放队列
首片: 第一句立即入队 (低首字延迟)
```

### 3.5 事件协议输出（V10.1.7）

```
事件: START / TOKEN / FLUSH / COMPLETE / INTERRUPTED / ERROR / HEARTBEAT
字段: conversation_id / turn_id / timestamp / sequence / event_type / payload
前端: sequence 单调递增校验, 旧 turn 事件丢弃, 禁止乱序/重复/覆盖
```

### 3.6 流式失败与回退

```
流式失败:
  1. 记录错误
  2. 标记当前 turn (ERROR)
  3. 执行定义好的 fallback
  4. 向前端发送明确 ERROR 事件
  5. 释放当前 turn
  6. 恢复 IDLE 或 READY

禁止 dispatcher 永久等待
Provider 不支持流式: 完整生成后一次性 Response (统一事件接口)
```

---

## 四、对话生命周期状态机

### 4.1 主路径

```
IDLE
  ↓ (输入接收)
RECEIVING
  ↓ (输入完成)
READY
  ↓ (开始处理)
PROCESSING
  ↓ (开始输出)
STREAMING
  ↓ (输出完成)
COMPLETED
  ↓ (释放)
IDLE
```

### 4.2 异常路径

```
PROCESSING / STREAMING
  ↓ (用户打断)
INTERRUPTED
  ↓ (队列推进 / 重新处理)
QUEUED / READY

任意状态:
  ↓ (错误)
ERROR
  ↓ (恢复)
IDLE / READY
```

### 4.3 状态迁移表

| 当前状态 | 可迁移到 |
|---|---|
| IDLE | RECEIVING |
| RECEIVING | READY, IDLE |
| READY | PROCESSING, QUEUED, IDLE |
| PROCESSING | STREAMING, INTERRUPTED, ERROR, IDLE |
| STREAMING | COMPLETED, INTERRUPTED, ERROR, IDLE |
| COMPLETED | IDLE, READY |
| INTERRUPTED | QUEUED, READY, IDLE |
| QUEUED | READY, IDLE |
| ERROR | IDLE, READY |

---

## 五、事件协议

### 5.1 事件格式

```json
{
  "conversation_id": "conv_xxx",
  "turn_id": "turn_xxx",
  "timestamp": 1786372088.97,
  "sequence": 1,
  "event_type": "START",
  "payload": {}
}
```

### 5.2 事件类型

| 事件 | 含义 | payload |
|---|---|---|
| START | turn 开始 | input |
| TOKEN | 文本增量 | content |
| FLUSH | 分段刷新 | — |
| COMPLETE | 完成 | full_content |
| INTERRUPTED | 中断 | — |
| ERROR | 错误 | error |
| HEARTBEAT | 心跳（如需要） | — |

### 5.3 前端渲染规则

```
sequence 单调递增 (防乱序)
旧 turn 事件 → 丢弃 (禁止旧回答覆盖新回答)
重复显示 → 禁止
乱序追加 → 禁止
```

---

## 六、数据流详解

### 6.1 文本对话流

```
用户输入 → WebUI Input Receiver → /api/chat/stream
  → webui_server SSE 透传 → backend /chat
    → Turn Controller (begin_turn → READY)
    → Context Manager (3 句窗口)
    → LLM Streaming (generate_stream)
    → 事件协议 SSE (START/TOKEN/COMPLETE)
  → WebUI Renderer (sequence 校验 + 显示)
  → (可选) 句级切分 → 并行 TTS → 顺序播放
```

### 6.2 语音对话流

```
麦克风 → vadRecorder (能量 VAD 状态机)
  → 说完检测 (尾音 6 帧 ~510ms)
  → 语音段 (纯语音帧 + 1s 预滚动)
  → 重采样 16kHz + 自适应增益
  → /api/transcribe (ASR)
  → 文本 → 防回声检测
  → voiceInputQueue (FIFO 排队)
  → sendToChat (同文本对话流)
  → streamPlayer 并行 TTS + 顺序播放
```

### 6.3 打断流

```
用户新输入 (PROCESSING/STREAMING 时)
  → Turn Controller: 新 turn begin (QUEUED)
  → 旧 turn interrupt (INTERRUPTED)
  → 前端: 停止旧输出 + 旧 turn 事件丢弃
  → 队列推进 → 新 turn READY → 处理
```

---

## 七、数值配置总表

### 7.1 前端（webui_templates/index.html）

| 常量 | 值 | 含义 |
|---|---|---|
| VAD_ENERGY_THRESHOLD | 0.015 | 语音能量阈值 |
| VAD_MIN_VOICED | 2 | 语音开始确认帧数 |
| VAD_MIN_UNVOICED | 2 | 静音确认帧数 |
| VAD_HANGOVER | 6 | 尾音缓冲帧数 (~510ms 采音周期) |
| VAD_MIN_SPEECH_MS | 300 | 最短语音段 |
| VAD_MAX_SPEECH_MS | 8000 | 最长录音 |
| VAD_PREROLL_MS | 1000 | 预滚动缓冲 |
| 增益目标 RMS | 0.06 | 自适应增益目标 |
| 增益上限 | 30x | 增益上限 |
| ECHO_OVERLAP_RATIO | 0.6 | 防回声重叠率 |
| 分句最小长度 | 4/8 | 标点断句 |
| 分句最大长度 | 50 | 强制断句 |
| 队列上限 | 20 | 输入队列 |

### 7.2 后端

| 配置 | 值 | 含义 |
|---|---|---|
| MAX_HISTORY_MESSAGES | 3 | 对话存储最多 3 句 |
| recent_messages | 3 | LLM 上下文最近 3 条 |
| 队列上限 | 20 | Turn 队列 |
| ASR 采样率 | 16000 | 识别输入 |
| TTS 引擎 | qwen3-tts-customvoice | 合成引擎 |
| TTS 采样率 | 24000 | 合成输出 |

---

## 八、可观察性与日志

### 8.1 延迟追踪（LatencyTracker 复用）

```
记录: input_start / input_end / turn_start / runtime_start
      / llm_start / first_token / stream_end
      / response_complete / turn_close / interrupt_time
计算: TTFT / Streaming Rate / Total Response Time
      / Queue Wait / Interrupt Latency / Turn Duration
      / Error Rate / Fallback Rate
```

### 8.2 Turn 日志（turn_id 可追踪）

```
关联: conversation_id / turn_id / request_id / model / provider
      / state transitions / latency / token usage
      / memory operation / error / fallback / interrupt
日志回答: 为什么慢 / 为什么没回复 / 为什么吃字
         / 为什么旧回答没停 / 为什么输入丢失 / 为什么乱序
```

### 8.3 WebUI 可观察状态

```
Runtime: Online / Offline
Conversation: Idle / Receiving / Processing / Streaming / Interrupted
LLM: Connected / Error
Memory: Active / Error
Current Turn: turn_id
TTFT: xxx ms
Response: Streaming / Complete / Error
最近错误: xxx
```

---

## 九、验收标准

### 9.1 必测场景（Test 01-12，全部 PASS）

```
Test 01 你好:              快速自然返回 ✅
Test 02 连续 20 轮:        上下文稳定 ✅
Test 03 长回复:            持续 Streaming ✅
Test 04 快速连续两条:      不丢消息 ✅
Test 05 生成中打断:        旧回复立即停止 ✅
Test 06 打断后继续:        上下文不污染 ✅
Test 07 Streaming 异常:    不永久卡住 ✅
Test 08 队列超限:          明确错误 ✅
Test 09 SSE 网络异常:      前端明确错误/恢复 ✅
Test 10 页面重连:          不产生重复 Turn ✅
Test 11 长时间运行:        无队列堆积/状态泄漏 ✅
Test 12 100 轮:            100/100, 平均 943ms ✅
```

### 9.2 热机通过条件（17 项）

```
✅ 可以正常输入 / 输入不丢失 / 不重复处理
✅ 首片快速出现 / Streaming 连续 / 不明显吃字
✅ 输出结束明确 / 支持打断 / 打断后上下文不污染
✅ 连续消息不丢失 / 异常可恢复 / 非流式有 Fallback
✅ WebUI 状态真实 / 每个 Turn 可追踪 / 错误可定位
✅ Runtime 可长期运行 / DEMO 交互体验不明显退化
```

### 9.3 失败判定（任一直接 NOT READY）

```
❌ 基础对话失败 / 输入丢失 / Streaming 永久卡死
❌ 打断失效 / 上下文污染 / Turn 状态失控
❌ 无法定位错误 / WebUI 显示与实际不一致
不得用其他模块通过抵消基础对话失败
```

---

**YHLZ · 元 · 亨 · 利 · 贞**

# YHLZ 2.0 链路与功能总览 · 待测试目标白皮书

> 版本：V10.1.3（热机阶段）
> 日期：2026-08-10
> 状态：WebUI :5000 + Backend :8000 运行中（qwen-turbo / ASR / TTS / VAD 在线）
> 用途：全链路功能盘点 + 待测试目标清单（热机验收依据）

---

## 目录

1. [系统全景](#一系统全景)
2. [链路总结](#二链路总结)
3. [功能清单](#三功能清单)
4. [待测试目标](#四待测试目标)
5. [测试优先级与验收](#五测试优先级与验收)
6. [当前已知问题与修复记录](#六当前已知问题与修复记录)

---

## 一、系统全景

```
┌──────────────────────────────────────────────────────────────┐
│  用户交互层                                                    │
│  ├─ WebUI 控制台 (webui_server.py :5000, 21 功能页)            │
│  ├─ 桌面伙伴壳 (frontend/main.py, 一键启动元亨)                │
│  └─ Live2D 桌宠 (live2d_desktop_avatar.py :8081/18765)        │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP :5000 (代理)
┌──────────────────────────▼───────────────────────────────────┐
│  Backend API 层 (backend/main.py :8000, FastAPI 121 路由)     │
│  chat/transcribe/synthesize/vad/voice(23)/personality(16)     │
│  perception(10)/understanding(9)/vision-memory(11)/agent(10)  │
│  action(9)/live2d(9)/memory(4)/modules(3)/sync(2)/tts(2)      │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│  能力引擎层                                                    │
│  ├─ LLM: qwen-turbo (DashScope, 百万 Token)                   │
│  ├─ ASR: funasr-SenseVoiceSmall (本地 cuda, 懒加载)           │
│  ├─ TTS: Qwen3-TTS-0.6B-CustomVoice (本地)                    │
│  ├─ VAD: Silero (实时语音活动检测)                             │
│  ├─ 模型池: ModelPoolRouter (V10.1.3, 5 模型调度)              │
│  ├─ Token优化: TokenOptimizer (V10.1.3, 压缩/缓存/预算)        │
│  ├─ 人类/多模态: HumanOperatorLayer + MultimodalLayer (V10.1.2)│
│  └─ Embodied 认知层: 记忆/反思/成长/治理/创造/研究/元认知       │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、链路总结

### L1. 系统启动链路（已验证 ✅）

```
start.bat
  └─ python webui_server.py (:5000)
       ├─ 浏览器自动打开 http://127.0.0.1:5000
       └─ POST /api/services/backend/start
            └─ 启动 backend/main.py (:8000)
                 ├─ 加载配置 → LLM(qwen-turbo) → TTS → VAD
                 ├─ ASR 懒加载 (首次语音请求时)
                 └─ wait_backend 监控: 60s 就绪 + 崩溃自动重启(≤3次)
```

**现状**：WebUI/Backend 运行中，健康判定"已连接"，后端 healthy。

### L2. 文本对话链路（已验证 ✅）

```
浏览器 → POST /api/chat/stream (SSE)
  → webui_server 代理 → backend /chat (SSE 流式)
    → Context Manager (上下文) → LLM (qwen-turbo)
    → SSE 逐字返回 → 前端流式显示
```

### L3. 语音对话链路（修复中 ⚠️ 重点测试）

```
浏览器 → getUserMedia(麦克风) → MediaRecorder.start(1000) 分片
  → 前端增益补偿 (INPUT_GAIN=8, 阈值 0.002)
  → POST /api/asr/transcribe (16kHz float32)
    → backend → audio_enhancer (谱减/归一化) → ASR (SenseVoiceSmall)
    → 识别文本 → POST /api/chat/stream → LLM 回复
    → TTS 合成 → 播放
```

**历史问题**：麦克风权限（已解决）→ 声音偏小（已加增益）→ MediaRecorder 无分片不产出数据（**已修复 start(1000)**，待验证）。

### L4. 声音克隆链路（已验证 ✅）

```
浏览器上传音频 → POST /api/voice/clone (multipart)
  → 质量门禁 → 去重检测 → 注册 voice_identity
  → 列表/详情/删除/批量克隆/审计
```

### L5. 记忆链路（✅ 引擎就绪）

```
事件 → Experience Store → 验证 (CONFIRMED)
  → Memory 分层 (index/importance/consolidation)
  → 记忆稳定化 (V10.1): 压缩/淘汰/权重/冲突
  → 健康指标联动 (Memory 维度)
```

### L6. 模型池调度链路（✅ V10.1.3 就绪）

```
请求 → TaskClassifier (8 类) → ModelSelector (评分)
  → Token 检查 (GREEN/YELLOW/RED) → 执行 → 调用记录
  → 异常/Token不足 → ModelHandoff (交接协议) → 备用模型
  → 主体连续性 (Identity Anchor 加载)
```

### L7. Token 优化链路（✅ V10.1.3 就绪）

```
输入 → 上下文筛选 → 对话压缩 (结论/决定/问题/下一步)
  → 响应缓存 (命中跳过) → Token 预算 (日/月/应急)
  → 效率指标 (Token 价值率)
```

### L8. 人类/多模态输入链路（✅ V10.1.2 就绪）

```
人类: 任务/反馈/体验/问题/想法 → HumanOperatorLayer → human_feedback/
多模态: camera/screen/audio/video/danmaku
  → 价值评分 (0-10) → 0-4 丢弃 / 5-7 短期 / 8-10 长期候选
  → 弹幕噪声过滤
```

### L9. 桌宠链路（待 GUI 验证）

```
后端 (TTS/情绪) → WebSocket (mouth_open/emotion/is_speaking)
  → AvatarWSClient → 渲染器 (口型/表情/视线/动作)
  → 前端一键启动 (frontend/main.py) → 元亨 ONLINE
```

### L10. 服务编排链路（已验证 ✅）

```
状态轮询: /api/status (端口/进程/标志三态探测)
启停: /api/services/<name>/start|stop|restart
崩溃恢复: wait_backend 自动重启 (≤3次)
关闭: /api/shutdown (avatar→live2d→backend→释放端口)
```

---

## 三、功能清单

### 3.1 对话与语音

| 功能 | 入口 | 状态 |
|---|---|---|
| 文本对话 | /api/chat/stream (SSE) | ✅ 已验证 |
| 语音对话 | /api/asr/transcribe + /api/chat/stream | ⚠️ 修复后待验证 |
| TTS 合成 | /synthesize | ✅ 已验证 |
| 语音打断 | /interrupt + /vad/* | ✅ 接口就绪 |
| 上下文管理 | Context Manager | ✅ |

### 3.2 声音身份（23 路由）

| 功能 | 状态 |
|---|---|
| 声音克隆 / 批量克隆 / 列表 / 详情 / 删除 | ✅ |
| 质量门禁 / 去重 / 音频播放 | ✅ |
| 审计 / 权限 / 生命周期 | ✅ |
| 适配器总览 / 指标 / 安全检测 | ✅ |

### 3.3 人格与记忆（16 + 4 路由）

| 功能 | 状态 |
|---|---|
| 人格配置 / 模板 / 风格 / 评估 / 上下文 | ✅ |
| 记忆增删查 / 搜索 | ✅ |
| 记忆稳定化 (压缩/淘汰/权重/冲突) | ✅ V10.1 |
| 交互协议 (会话状态/工具流/伙伴状态) | ✅ V10.1 |

### 3.4 感知与视觉

| 功能 | 状态 |
|---|---|
| 感知 (OCR/检测/屏幕/权限) | ✅ 10 路由 |
| 理解 (描述/问答/屏幕) | ✅ 9 路由 |
| 视觉记忆 (保存/查询/上下文) | ✅ 11 路由 |

### 3.5 Agent 与行动

| 功能 | 状态 |
|---|---|
| Agent 对话/规划/工具/记忆 | ✅ 10 路由 |
| 行动请求/状态/取消/历史 | ✅ 9 路由 |

### 3.6 认知层（Embodied 8559 测试）

```
记忆/反思/成长/治理/创造/研究/元认知/稳定化/交互协议
+ 热机健康指标 (四维) + 模型池 + Token优化 + 人类/多模态
```

### 3.7 前端

| 功能 | 状态 |
|---|---|
| WebUI 21 功能页 | ✅ |
| 桌面伙伴壳 (一键启动元亨) | ✅ |
| 开发模式 (Ctrl+Shift+R) | ✅ |
| Live2D 桌宠 (4 版本) | 待 GUI 验证 |

---

## 四、待测试目标

### 4.1 P0 优先级（热机运行必需，阻塞项）

| 编号 | 目标 | 链路 | 当前状态 | 测试方法 |
|---|---|---|---|---|
| T-01 | **语音对话端到端**（说话→识别→回复→朗读） | L3 | ⚠️ 修复后待验证 | 浏览器实际说话测试 |
| T-02 | 语音识别准确性（正常音量/偏小音量） | L3 | ⚠️ | 说话→检查 /transcribe 返回 |
| T-03 | 语音对话连续多轮（边说边识别稳定性） | L3 | ⚠️ | 连续 5 轮对话 |
| T-04 | 停止对话后资源释放（录音流/识别） | L3 | ⚠️ | 点结束→检查无残留 |
| T-05 | TTS 朗读回复（语音对话模式） | L3 | ⚠️ | 说话→听回复 |
| T-06 | 麦克风增益补偿效果（声音偏小时） | L3 | ⚠️ | 小声说话→识别 |
| T-07 | 72h 连续运行 Crash=0 | L1 | ⏳ 待执行 | 挂机观察 |

### 4.2 P1 优先级（核心功能完善）

| 编号 | 目标 | 链路 | 当前状态 | 测试方法 |
|---|---|---|---|---|
| T-08 | 文本对话 20 轮上下文连续性 | L2 | ✅ 基础过 | 多轮对话检查记忆 |
| T-09 | 语音克隆完整流程（上传→克隆→使用） | L4 | ✅ 接口过 | 实际克隆 1 个音色 |
| T-10 | 声音质量门禁拦截低质音频 | L4 | ✅ 接口过 | 传噪音音频 |
| T-11 | 记忆稳定化（压缩/淘汰/冲突）实际数据 | L5 | ✅ 引擎过 | 注入重复/冲突记忆 |
| T-12 | 模型池自动切换（模拟 Token 耗尽） | L6 | ✅ 引擎过 | 调 check_and_switch |
| T-13 | Token 优化（压缩/缓存/预算）实际调用 | L7 | ✅ 引擎过 | 调 TokenOptimizer |
| T-14 | 人类每日反馈写入 human_feedback/ | L8 | ✅ 引擎过 | 调 daily_feedback |
| T-15 | 多模态价值评分（高/中/低/弹幕噪声） | L8 | ✅ 引擎过 | 调 process |
| T-16 | 崩溃自动重启（kill 后端→恢复） | L10 | ✅ 已过 | kill→15s 内恢复 |
| T-17 | 多实例防护（双 WebUI 抢端口） | L10 | ✅ 已过 | 双启动 |
| T-18 | 优雅关闭与重启恢复 | L10 | ✅ 已过 | shutdown→重启 |

### 4.3 P2 优先级（增强与 GUI）

| 编号 | 目标 | 链路 | 当前状态 | 测试方法 |
|---|---|---|---|---|
| T-19 | 桌面伙伴壳 GUI 一键启动元亨 | L9 | ✅ 已过(offscreen) | 真实 GUI 启动 |
| T-20 | Live2D 桌宠加载与口型同步 | L9 | ⏳ 待 GUI | 启动桌宠说话 |
| T-21 | 视觉感知（屏幕 OCR/检测） | 感知 | ⏳ 需权限 | 授权后测试 |
| T-22 | 摄像头采集与理解 | 感知 | ⏳ 需权限 | 授权后测试 |
| T-23 | 声音身份跨会话保持 | L4 | ✅ 接口过 | 重启后音色在 |
| T-24 | 记忆持久化重启恢复 | L5 | ✅ 接口过 | save→load |
| T-25 | 健康指标四维报告 | 认知 | ✅ 引擎过 | companion_health |
| T-26 | 前端 21 页完整功能 | WebUI | ⚠️ 逐页 | 逐页点击验证 |

### 4.4 回归目标（每次改动后）

| 编号 | 目标 | 命令 |
|---|---|---|
| R-01 | Embodied 8559 用例 | `venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests` |
| R-02 | 前端 118 用例 | `venv\Scripts\python.exe -m unittest discover -s frontend.tests -p "test_*.py"` |
| R-03 | 其他子系统 | vision/action/agent/personality/voice_identity |
| R-04 | 全量 9413 用例 Failed=0 | 汇总 |

---

## 五、测试优先级与验收

### 执行顺序

```
第 1 步: T-01~T-06 (语音对话链路, 当前修复验证) ← 立即
第 2 步: R-01~R-04 (全量回归, 确认修复无破坏)
第 3 步: T-08~T-18 (P1 核心功能验收)
第 4 步: T-19~T-26 (P2 GUI/增强)
第 5 步: T-07 (72h 长期运行)
```

### 验收标准（热机 8 级）

```
Identity ≥99% | Constitution 0 违反 | Memory 有效>无效
Runtime 72h Crash=0 | Observability 全追踪
Frontend 一键启动 | Performance 普通<2s/复杂<5s
Maintenance Log/Trace/Recovery/Rollback
```

---

## 六、当前已知问题与修复记录

### 已修复

| 日期 | 问题 | 修复 | 状态 |
|---|---|---|---|
| 08-10 | UI 显示"后端异常"（healthy vs ok 不一致） | /api/health 归一化 | ✅ 已验证 |
| 08-10 | /api/chat 500（SSE 解析失败） | SSE 透传 | ✅ 已验证 |
| 08-10 | 麦克风权限被拒 | 系统/浏览器授权 | ✅ 已解决 |
| 08-10 | 声音偏小被静音拦截 | 前端增益 8x + 阈值 0.002 | ✅ 已部署 |
| 08-10 | **语音对话无反应（MediaRecorder 无分片）** | start(1000) 分片 + 防重入 | ⚠️ 待验证 |

### 待处理

| 问题 | 影响 | 计划 |
|---|---|---|
| 语音对话链路端到端验证 | 热机核心功能 | T-01~T-06 立即测试 |
| WebUI 重启后不接管已有后端 | 崩溃监控缺口 | 记录 GAP-1, 热机后处理 |
| ASR 懒加载首次延迟 | 首次语音等待数秒 | 可接受, 记录 |

---

**YHLZ · 元 · 亨 · 利 · 贞**

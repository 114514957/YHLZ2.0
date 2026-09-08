# YHLZ WebUI 全功能控制台 · 设计方案 v1（0219）

> 状态：设计稿（未开工）。依据 0219 全链路校验结论与用户选型：**后端直采音频 + 网页仅控制/文本/状态/日志**、**全功能控制台**、本地 127.0.0.1 单机使用。

## 0. 背景与依据（校验产出，0219/0220）
- 语音链已验证可用：RNNoise 前端(48k→16k) + SenseVoiceSmall 整段 ASR(素材 345 字通顺) + sherpa 兜底(1.9s 加载) + 本地 Gemma LLM(人格已修) + Qwen3-TTS(合成正常)。
- 关键约束（实测）：8.6GB 单卡，**ASR / LLM(8081 llama) / TTS 不可同时驻留**（free 到 0）；已验证**顺序释放策略可行**（SenseVoice 用完释放→TTS 加载合成 OK）。→ 控制台必须内建模型调度，禁止并发驻留。
- 声纹门：RNNoise 清噪在本机有效 → 默认关闭；保留可选。
- QQ 多渠道：挂起，仅记录不纳入本次 WebUI。

## 1. 目标与原则
1. 一个本地控制台收束 YHLZ 主要能力：语音/文本对话、记忆、计划、会话档案、服务与日志。
2. 后端直采音频：麦克风采集、VAD、ASR、TTS 全部在服务端进程；浏览器零音频处理（无 WebAudio 依赖），便于 8G 单机资源统一调度。
3. 复用既有资产：target_daemon(8321)、ConversationSession/run_turn、工具/计划表、memory、流式 SSE、Qwen3-TTS、SenseVoice、RNNoise。不重写核心。
4. 一切敏感写入（记忆/认知/工具副作用）沿用 y/n 审批文化（经 ws 弹窗确认）。

## 2. 运行形态与进程拓扑
- 单控制进程 **WebConsole**（并入 daemon 同进程更佳，或 daemon 8321 上新增 /webui 路由+WS，最省）：
  - HTTP 静态服务单页 + REST
  - WebSocket 状态/事件推送
  - 内部：`VoiceDialogRuntime`（采集线程，独立于 asyncio）、`ModelScheduler`（ASR/TTS/LLM 显存排他）、`SessionBridge`(调 ConversationSession)
- LLM：沿用 8081 llama-server（独立进程常驻，persona 已固化）
- 采样：声卡输入线程 48k → RNNoise(neko processor) → 16k → SenseVoice（载入阶段独占）

## 3. 页面布局（单页控制台）
- **顶栏**：服务状态灯(8081 gemma / ollama / 8321 / ASR / TTS) + 模型占用提示 + 设置入口
- **左主区 · 对话**：气泡流（user/yuanheng）；说话人标识；VAD 电平条(实时)；阶段状态灯 正在听·想·说；打断/停止按钮
- **右 Tabs**：
  - 记忆：关键词检索/最近 L2 列表/置信度/降档记录
  - 计划表：/tool/schedule 看板（list/create/toggle）
  - 会话档案：recent_sessions 列表 → 加载/新开/导出
  - 技能与工具：capability 面
  - 日志：滚动实时
- **底部**：文本输入(回车对话) | 语音键(按住说 / 常开聆听开关) | 快捷命令

## 4. 对话状态机（Turn）
```
idle ──(文本/语音触发)──> listening (采集+VAD, 说完停3s断句)
listening ──> asr (SenseVoice, 独占) ──> thinking (Gemma 流式 → 气泡)
thinking ──> speaking (Qwen3-TTS 按需载入+播放, 流式句切)
speaking ──(VAD 检测到用户开口, 中断阈值)──> listening   (barge-in 打断)
任意 ──> idle
```
回声抑制：speaking 期间采集线程暂停；speaking 结束+消隐后再回 listening。

## 5. 接口设计（草案）
- REST（在 8321 daemon 上扩展）：
  - `GET  /webui/state` 全状态
  - `POST /webui/talk {text, mode?}` 文本轮（复用 run_turn）
  - `POST /webui/voice {action: start|stop|toggle_listen}`
  - `GET  /webui/memory?q=` 检索；`GET /webui/sessions`
  - 复用：`/turn`、`/v1/chat/completions`、`/tool/schedule`、`/notifications`
- WebSocket `/webui/ws` 上行：text/voice/approval 回执/设置
  下行事件：`{type}` ∈ `state|delta(text增量)|turn_done|vad(电平)|log|memory_changed|approval_request`
- 审批：side-effect 工具先推 `approval_request`，前端弹窗 → 回 `approval` → 原 approver 完成。

## 6. ModelScheduler（8G 显存排他，校验实证）
- 规则：同一时刻最多一个"大 cuda 占用者"（SenseVoice ~1-2G / Qwen3-TTS ~3.5G）+ llama 常驻。
- 进入 listening→asr：ensure ASR(载 sv)，TTS 必须已释放。
- 进入 speaking：先 release_sv/释放 ASR，再 ensure TTS；播完释放。
- llama：`-ngl` 与 TTS 共存实测 ok（≈7.2/8.6）；若仍紧，策略选项（记录，实施时定）：
  a) TTS 换 0.6B(更快更小)  b) llama 降 ngl  c) TTS 长文缓存复用
- 暴露 `/webui/state.model` 显示占用，便于观察。

## 7. 里程碑（后续，非本轮）
- M1 控制台壳：静态单页+WS+状态灯+文本对话流式显示（复用 daemon）
- M2 语音接入：VoiceDialogRuntime 采集/VAD/打断 + 语音键 + ModelScheduler
- M3 数据 tab：记忆/计划/会话档案/日志
- M4 打磨：设置面板、审批流、barge-in 手感、音量电平可视化、模型策略选项

## 8. 边界与安全
- 仅监听 127.0.0.1；无公网暴露。
- 记忆/计划/认知等写操作一律经审批；日志与响应脱敏（无 API key/口令明文）。
- 本轮只设计不实现。

## 9. 校验记录（0219/0220 摘要，详见台账）
- 回归 393 全绿；文本/SSE/记忆/计划/工具面 27/会话档案/persona 全 PASS。
- 语音链：sherpa 1.9s 加载、SenseVoice 素材整段 345 字、素材→LLM、声纹自比对 sim0.778 PASS。
- Qwen3-TTS 合成 PASS；VRAM free0 → 顺序释放策略 E1-E5 实证可行并已修入 voice_dialog。
- 记录项：技术长文转述会命中 auto-work 词(工具化倾向，minor)；QQ 线挂起仅记录。

# YHLZ 对话链路对比分析：对话DEMO vs 当前系统

> 日期：2026-08-10 | 版本：V10.1.5
> 目的：对比对话DEMO（voice_chat_demo.py）与当前系统（WebUI+Backend）的对话链路差异

---

## 一、总体结论

**用户的判断正确：对话DEMO 的链路在语音对话体验上确实优于当前系统。**

核心差距：

| 维度 | 对话DEMO | 当前系统 | 差距 |
|---|---|---|---|
| 语音识别触发 | VAD 实时检测（说完自动识别） | 固定 1 秒分片盲发 | DEMO 优 |
| 打断（barge-in） | 完整 token 令牌 + 音量遮蔽 | ❌ 无 | DEMO 优 |
| 回声防护 | 音量遮蔽 + 防循环检测 | ❌ 无 | DEMO 优 |
| TTS 播放 | 并行预合成 + 顺序播放（无卡顿） | ❌ 手动按钮/未播放 | DEMO 优 |
| 延迟追踪 | LatencyTracker 全阶段 | 无前端追踪 | DEMO 优 |
| 系统架构 | 单进程 CLI（不适用 Web） | WebUI 浏览器架构 | 当前优 |

---

## 二、链路逐环节对比

### 2.1 语音采集与识别触发

```
DEMO (Recorder + VAD):
  麦克风 → 每帧 VAD 检测 (Silero detect_speech)
    → 检测到语音开始 (含预滚动缓冲, 防丢开头)
    → 持续采集
    → VAD 判定说完 (is_speaking=False) → 整段语音
    → ASR 识别

当前系统 (WebUI MediaRecorder):
  麦克风 → getUserMedia → MediaRecorder.start(1000)
    → 每秒固定 1 秒分片 (无 VAD 判断)
    → 每块静音检测 (RMS<0.002 跳过)
    → 非静音块 → ASR 识别
```

**差异**：
- DEMO：VAD 检测**完整语音段**（说完才识别，语音完整），预滚动防丢字
- 当前：固定分片（1 秒），**可能切半句话**；识别零散块；无预滚动

### 2.2 打断与插话（barge-in）

```
DEMO:
  _gen_token 令牌机制: 每轮生成唯一 token
  interrupted() = token 变化 → 立即停止 LLM/TTS
  播放期间: 音量遮蔽 (用户声音 > AI播放音量 × ECHO_GAIN_RATIO 才算插话)
  插话入队 (pending_segments), 不打断播放, 播完再处理
  防回声: _is_echo 文本重叠检测 (丢弃 ASR 回声)

当前系统:
  ❌ 无打断机制
  ❌ 无插话处理
  ❌ 无回声防护
  (后端有 /interrupt 接口但前端未接入)
```

### 2.3 TTS 合成与播放

```
DEMO (并行预合成 + 顺序播放):
  LLM 流式 → 句级切分 (min_segment_length=4)
    → 每句独立 asyncio task 并行合成 (stream_synthesize_text)
    → play_queue → dispatcher 按 seq 顺序入队
    → Player 顺序播放 (首片 0.17s 即入队, 低首字延迟)
    → 段结束哨兵 (失败不卡 dispatcher)

当前系统:
  Backend: LLM 流式 → 断句 → tts_producer 合成 → audio_buffer
  WebUI: sendToChat 只显示文本 (不消费 audio_buffer)
    → 语音对话中 AI 回复不自动朗读!
  playPCM 仅用于手动"朗读最后回复"按钮
```

**关键缺陷**：当前系统 WebUI 语音对话**没有自动 TTS 播放链路**（后端合成进 buffer，前端无消费端），这是与 DEMO 最大的体验差距。

### 2.4 延迟追踪

```
DEMO: LatencyTracker (vad_start/vad_end/asr_start/asr_done/
      llm_start/llm_first/tts_start/tts_done/play_start)
当前: 后端有 metrics 接口, 前端无逐阶段追踪
```

---

## 三、DEMO 可吸收机制清单（按价值排序）

| # | 机制 | 价值 | 吸收难度 | 说明 |
|---|---|---|---|---|
| 1 | **自动 TTS 播放链路**（前端消费 audio_buffer） | 极高 | 中 | 语音对话必须自动朗读 |
| 2 | **VAD 说完自动识别**（完整语音段） | 高 | 高 | 需前端接入 Silero VAD 或后端流式 ASR |
| 3 | **并行预合成 + 顺序播放**（句级切分） | 高 | 中 | 消除句间卡顿 |
| 4 | **barge-in 打断令牌** | 高 | 中 | 后端已有 /interrupt 接口 |
| 5 | **音量遮蔽回声防护** | 高 | 中 | 播放时过滤回声 |
| 6 | **LatencyTracker 前端化** | 中 | 低 | 逐阶段显示延迟 |
| 7 | **段结束哨兵**（失败不卡顿） | 中 | 低 | 已内建于后端 |

---

## 四、当前系统优势（不应放弃）

| 优势 | 说明 |
|---|---|
| 浏览器 Web 架构 | 免安装、跨设备、多页功能（克隆/记忆/人格/设置） |
| 多模态能力 | 视觉/感知/理解已接入（DEMO 无） |
| 认知伙伴层 | 记忆/反思/成长/治理（DEMO 无） |
| 模型池 + Token 优化 | 多模型调度与成本控制（DEMO 无） |
| 服务编排 | 启停/监控/崩溃恢复（DEMO 无） |

---

## 五、建议方案

**吸收 DEMO 语音体验机制到当前 WebUI 语音对话链路（热机后执行，非阻塞）：**

### 方案 A：前端自动 TTS 播放（P0，优先）

```
当前: sendToChat 只显示文本
改为: SSE 流式对话时, 前端从后端消费 TTS 音频
实现:
  1. 后端 /chat 增加音频流通道 (SSE 中带 base64 音频块, 或独立 /audio/stream WS)
  2. 前端收到音频块 → playPCM 立即播放 (队列顺序)
  3. 支持 interrupt (用户说话 → 停止播放)
```

### 方案 B：说完自动识别（P1）

```
当前: 固定 1 秒分片
改为: 前端接入 VAD (Silero WASM 或轻量能量检测)
  检测到语音开始 → 开始采集
  检测到说完 (静音 400ms) → 整段发送 ASR
  或: 后端流式 ASR (WebSocket 逐帧识别)
```

### 方案 C：barge-in + 回声防护（P1）

```
前端: 播放时记录 AI 音量 → 用户音量 > AI×1.5 才接受为新语音
后端: /interrupt 接口接入前端
防回声: 识别文本与最近 AI 回复重叠率 > 阈值 → 丢弃
```

### 方案 D：并行预合成（P2）

```
前端: 收到完整句子 → 立即调 /tts/synthesize (并行)
  按顺序播放 (AudioContext 队列)
或: 后端 tts_producer 已并行, 前端保证顺序消费即可
```

---

## 六、结论

| 项 | 判定 |
|---|---|
| DEMO 链路是否更优 | ✅ 是（语音对话体验维度） |
| 主要差距 | ①自动TTS播放缺失 ②VAD说完识别 ③打断/回声 |
| 当前系统优势 | 架构/多模态/认知/编排（保留） |
| 建议 | 热机后按方案 A→B→C→D 吸收，**不阻塞当前热机运行** |

**YHLZ 定位不变**：DEMO 的交互机制是"零件"，当前系统的认知架构是"主体"——吸收零件，强化主体。

---

**YHLZ · 元 · 亨 · 利 · 贞**

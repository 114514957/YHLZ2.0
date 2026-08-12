# YHLZ 语音对话流式规则白皮书

> 版本：V10.1.5（DEMO 流模式集成版）
> 日期：2026-08-10
> 依据：对话DEMO（voice_chat_demo.py）流式机制 + 当前 WebUI 集成

---

## 目录

1. [流式架构总览](#一流式架构总览)
2. [采集规则（麦克风 → 语音段）](#二采集规则麦克风--语音段)
3. [识别规则（语音段 → 文本）](#三识别规则语音段--文本)
4. [对话存储规则（3 句滑动窗口）](#四对话存储规则3-句滑动窗口)
5. [生成规则（LLM 流式 → 句级切分）](#五生成规则llm-流式--句级切分)
6. [播放规则（并行预合成 + 顺序播放）](#六播放规则并行预合成--顺序播放)
7. [打断与回声规则](#七打断与回声规则)
8. [队列与输出规则](#八队列与输出规则)
9. [数值配置总表](#九数值配置总表)
10. [与 DEMO 差异说明](#十与-demo-差异说明)

---

## 一、流式架构总览

```
麦克风
  ↓ 采集 (ScriptProcessor 4096帧/48kHz)
  ↓ VAD 状态机 (能量检测 0.015)
  ↓ 说完判定 (尾音 6 帧 ~510ms)
  ↓ 语音段 (纯语音帧 + 1s 预滚动)
  ↓ 重采样 16kHz + 自适应增益
  ↓ ASR 识别 (SenseVoiceSmall)
  ↓ 文本
  ↓ [输入队列 FIFO] ← 按输入顺序排队
  ↓ 防回声检测 (重叠率 > 60% 丢弃)
  ↓ LLM 流式生成 (qwen-turbo)
  ↓ 句级切分 (标点断句)
  ↓ 并行预合成 TTS (每句独立请求)
  ↓ 顺序播放队列 (seq 递增, onended 驱动)
  ↓ 扬声器
```

---

## 二、采集规则（麦克风 → 语音段）

### 2.1 采集参数

| 参数 | 值 | 说明 |
|---|---|---|
| 采集器 | ScriptProcessor 4096 帧 | 兼容性最好的浏览器方案 |
| 采样率 | 48kHz（浏览器原生） | 后续重采样 16kHz |
| 帧时长 | ~85ms/帧 | 4096/48000×1000 |

### 2.2 VAD 状态机（沿用 DEMO 数值）

```
状态: silence → speaking → hangover → silence

silence (静音):
  能量 RMS > 0.015 连续 2 帧 (VAD_MIN_VOICED) → 进入 speaking
  语音开始: 包含 1 秒预滚动缓冲 (VAD_PREROLL_MS), 防丢开头字

speaking (说话中):
  语音帧持续累积 (静音帧不累积, 只计数)
  连续 2 帧静音 (VAD_MIN_UNVOICED) → 进入 hangover
  超时 8 秒 (VAD_MAX_SPEECH_MS) → 强制发送

hangover (尾音缓冲):
  语音恢复 → 回到 speaking
  连续 6 帧静音 (VAD_HANGOVER ≈ 510ms) → 判定说完 → 发送
```

**采音周期延长**：尾音缓冲从 1 帧（~85ms）延长至 **6 帧（~510ms）**，说话中的自然停顿不会被误判为说完，语音段更完整。

### 2.3 语音段处理

```
帧处理:
  只累积语音帧 (静音帧不进入语音段, 仿 DEMO Recorder)
  预滚动: 保留最近 1s 音频, 语音开始时包含前置帧

发送前处理:
  合并全部帧 → 重采样 16kHz
  自适应增益: 目标 RMS 0.06, 增益上限 30x
    (gain = min(30, 0.06 / rawRms), 声音小自动放大)
  最短语音段: < 300ms 丢弃 (VAD_MIN_SPEECH_MS)
  静音兜底: RMS < 0.01 丢弃
```

---

## 三、识别规则（语音段 → 文本）

| 参数 | 值 | 说明 |
|---|---|---|
| 接口 | POST /transcribe | 16kHz float32 |
| 模型 | funasr-SenseVoiceSmall | 本地 GPU 懒加载 |
| 引擎 | ASR ThreadPoolExecutor | 重启后正常 |
| 识别失败 | 返回空文本 | 前端提示"未识别到语音内容" |

识别结果处理：
1. 空文本 → 提示"未识别到语音内容"，不输出
2. **防回声检测** → 与最近 AI 回复重叠率 > 60% → 丢弃
3. 通过 → 显示用户消息 → **入输入队列**

---

## 四、对话存储规则（3 句滑动窗口）

### 4.1 后端存储（context_manager）

```
规则: 最多保留最近 3 条消息 (MAX_HISTORY_MESSAGES = 3)
实现: add_message 时超出 3 条 → 丢弃最旧
效果: 对话存储满 3 句后, 只输出这 3 句
      其他输入仍被接收进链路 (识别/入队), 但上下文自动滑出旧句
```

### 4.2 上下文构建

```
/chat 调用: get_context(recent_messages=3)
消息组成: system(人格) + 最近 3 条对话
验证: 连续 5 句后, 发送给 LLM = system + 3 句
```

---

## 五、生成规则（LLM 流式 → 句级切分）

### 5.1 LLM 流式

```
接口: POST /chat (SSE 流式)
模型: qwen-turbo (DashScope)
输出: data: {"content": "..."} 逐块
```

### 5.2 句级切分（splitTextForStreaming）

```
规则 (仿 DEMO split_text_for_streaming):
  句号/问号/感叹号/分号/省略号 (。！？；!?;…) → 断句 (≥4字)
  逗号/顿号 (，、,) → 断句 (≥8字)
  50 字无标点 → 强制断句

目的: 句子尽早产出, 供 TTS 并行预合成, 消除句间卡顿
```

---

## 六、播放规则（并行预合成 + 顺序播放）

### 6.1 并行预合成（streamPlayer.preSynth）

```
每句独立发起 POST /api/tts/synthesize (并行)
  → 不等上一句播完, 下一句 TTS 已在合成
  → 首句优先 (第一句立即入队, 低首字延迟)
失败处理: 合成失败 → 失败哨兵, 不卡播放队列
```

### 6.2 顺序播放（streamPlayer._dispatch）

```
队列: seq 递增 (0,1,2,...)
规则: 只有 next 就绪才播放 (dispatcher 语义)
  - 下一个 seq 未完成 → 等待
  - 完成后 → onended 驱动继续
  - 失败哨兵 → 跳过继续
效果: 输出严格按输入/生成顺序, 不乱序
```

### 6.3 TTS 参数

```
接口: POST /api/tts/synthesize
引擎: qwen3-tts-customvoice (本地克隆版)
音色: Vivian (默认)
语速: 0% (正常)
```

---

## 七、打断与回声规则

### 7.1 barge-in 打断

```
触发: VAD 检测到新语音开始 (2 帧确认)
动作: streamPlayer.interrupt()
  - 停止当前播放 (source.stop())
  - 清空待播放队列
  - 后续 preSynth 结果丢弃 (interrupted 标记)
效果: 用户说话立即打断 AI 朗读
```

### 7.2 防回声（ECHO_OVERLAP_RATIO = 0.6）

```
规则 (仿 DEMO _is_echo):
  识别文本 vs 最近 AI 回复
  字符重叠率 > 60% 且文本 > 4 字 → 判回声 → 丢弃
效果: 防止 ASR 识别到 AI 播放声音形成死循环
```

### 7.3 音量遮蔽（DEMO 参考, 当前未启用）

```
DEMO 有: 插话 RMS > AI播放音量 × 1.6 才算语音 (ECHO_GAIN_RATIO)
当前: 依赖防回声文本检测 (未做音量遮蔽, 列为后续增强)
```

---

## 八、队列与输出规则

### 8.1 输入队列（voiceInputQueue）

```
规则: FIFO 先进先出
实现: 每句识别结果 push → processVoiceQueue 串行处理
效果:
  - 按输入顺序排队输出 (严格顺序)
  - 每句只输出一遍 (串行天然保证)
  - 停止对话时清空队列
```

### 8.2 输出保证

```
每个输入: 识别 → 入队 → LLM → 句切分 → TTS → 播放, 只走一遍
上下文: 滑动 3 句窗口 (旧句滑出)
```

---

## 九、数值配置总表

### 9.1 前端（webui_templates/index.html）

| 常量 | 值 | 含义 | 来源 |
|---|---|---|---|
| VAD_ENERGY_THRESHOLD | 0.015 | 语音能量阈值 | DEMO vad_engine |
| VAD_MIN_VOICED | 2 | 语音开始确认帧数 | DEMO |
| VAD_MIN_UNVOICED | 2 | 静音确认帧数 | DEMO |
| VAD_HANGOVER | 6 | 尾音缓冲帧数 (~510ms) | 采音周期延长 |
| VAD_MIN_SPEECH_MS | 300 | 最短语音段 | DEMO 0.3s |
| VAD_MAX_SPEECH_MS | 8000 | 最长录音 | DEMO 8s |
| VAD_PREROLL_MS | 1000 | 预滚动缓冲 | DEMO preroll |
| 增益目标 RMS | 0.06 | 自适应增益目标 | 声音偏小补偿 |
| 增益上限 | 30x | 增益上限 | 防削顶 |
| ECHO_OVERLAP_RATIO | 0.6 | 防回声重叠率 | DEMO |
| 分句最小长度 | 4/8 | 标点断句阈值 | DEMO |
| 分句最大长度 | 50 | 无标点强制断句 | DEMO |

### 9.2 后端（context_manager / main.py）

| 配置 | 值 | 含义 |
|---|---|---|
| MAX_HISTORY_MESSAGES | 3 | 对话存储最多 3 句 |
| recent_messages | 3 | LLM 上下文最近 3 条 |
| ASR 采样率 | 16000 | 识别输入 |
| TTS 引擎 | qwen3-tts-customvoice | 合成引擎 |

### 9.3 DEMO 对照（voice_chat_demo.py）

| DEMO 常量 | 值 | 当前系统 |
|---|---|---|
| SAMPLE_RATE | 16000 | ✅ 同 |
| FRAME_SIZE | 1600 (100ms) | 浏览器 4096 (~85ms) |
| SILENCE_TIMEOUT | 8.0s | ✅ 同 (VAD_MAX_SPEECH_MS) |
| MIN_SPEECH_DURATION | 0.3s | ✅ 同 |
| ECHO_GAIN_RATIO | 1.6 | ⏳ 未启用 (待增强) |
| ECHO_OVERLAP_RATIO | 0.6 | ✅ 同 |
| LLM 历史 | 最近 8 条 | 当前 3 条 (按需求) |

---

## 十、与 DEMO 差异说明

| 维度 | DEMO | 当前系统 | 说明 |
|---|---|---|---|
| 采集 | sounddevice 流式 | 浏览器 ScriptProcessor | 平台差异 |
| VAD | Silero/能量引擎 | 前端能量状态机 | 数值沿用 |
| 说完判定 | VAD is_speaking | 尾音 6 帧 (~510ms) | 采音周期延长 |
| 上下文 | 最近 8 条 | 最近 3 条 | 按需求: 3 句存储 |
| 输出顺序 | dispatcher 队列 | 输入队列 + 播放队列 | 双队列保证 |
| 输出次数 | 每句一次 | 每句一次 (串行) | 只输出一遍 |
| 音量遮蔽 | 有 (1.6x) | 未启用 | 待增强 |
| 延迟追踪 | LatencyTracker | 无前端追踪 | 待增强 |

---

**YHLZ · 元 · 亨 · 利 · 贞**

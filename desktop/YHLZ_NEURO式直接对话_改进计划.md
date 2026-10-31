# YHLZ「NEURO 式直接对话」改进计划

**版本**：v1.0
**制定日期**：2026-09-27
**适用项目**：`C:\Users\ACE_WAN——PROJECT\YHLZ`
**目标**：在 RTX 4060 Laptop 8GB、当前本地 Gemma + Sherpa/SenseVoice + Qwen3-TTS 架构上，先做出“像 NEURO 一样可以直接说、马上听到回答、可以插话”的稳定体验；不再继续做没有验收标准的“大而全端到端”。

---

## 一、先说结论：现在不要继续硬做“纯端到端语音模型”

你现在最应该走的路线不是：

> 麦克风 → 一个端到端模型 → 直接生成声音

而是：

> **同一个会话状态机 + 流式语音前端 + 本地 LLM 流式回答 + 可打断 TTS 播放**

这条路线表面上仍然是 ASR 链，但用户感受会接近“直接对话”。关键不在于彻底消灭 ASR，而在于把 ASR 变成后台的低延迟感知层，让用户不用等“录音结束、识别完成、模型回答完成、整段语音合成完成”这四个长步骤。

### 你现在遇到问题的根本原因

1. **项目里同时存在两套语音链路**：
   - 工作台实际入口是 `backend/console_server.py` 的 `/voice`。
   - 另一套较新的目标架构在 `backend/target_chain.py`、`backend/streaming_asr_bridge.py`、`backend/session_kernel.py`、`backend/target_runtime.py`、`backend/target_composition.py` 中。
   - 两套链路还没有真正合并，所以你改了一边，另一边不一定生效。

2. **当前 `/voice` 仍然混用了旧式捕获和新式 Sherpa partial**：
   - `_do_voice()` 通过 `tools.tts_test_start._capture_loop` 收音。
   - Sherpa 只负责显示 partial，最终提交给 LLM 的仍主要是 SenseVoice 的整段结果。
   - 这意味着界面看起来“在流式识别”，但真正的对话提交还是“等一句话结束后再整段识别”。

3. **每轮释放/重新获取 ASR，加大了延迟和不稳定性**：
   - 当前代码在每轮结束后 `release_sv()`。
   - 这会让模型加载、显存/内存回收、线程切换和下一轮重新初始化影响连续对话。

4. **现在的打断主要靠音量阈值，不是真正的回声控制**：
   - `_StreamingSpeaker` 一边 `sd.play()`，一边用输入 RMS 判断用户有没有讲话。
   - 没有把“正在播放的声音”作为参考信号做 AEC/回声抑制，扬声器声音可能被误判成用户插话。
   - 中断后虽然有 `sd.stop()` 的兜底，但播放控制、输入控制和回合取消还没有完全由同一个 turn owner 管理。

5. **纯音频直入目前不能作为主链路**：
   - `tools/voice_dialog_probe.py --engine audio` 和 `tools/voice_latency_bench.py` 可以做实验。
   - 但把 `input_audio` 直接送给当前本地 LLM，不等于已经有一个可靠的语音对话模型。它可能没有稳定的语音识别、端点检测、工具调用、记忆写入和打断语义。
   - 所以它暂时只能做 A/B 对照，不能替代主链。

**最终策略：先做“混合实时链路”，等它稳定后，再把真正的端到端模型作为可插拔 Provider 接入。**

---

## 二、你要达到的“NEURO 式效果”到底是什么

不要把目标写成“必须端到端”。真正需要验收的是下面这些用户体验：

| 用户感受 | 工程指标（第一版目标） |
|---|---|
| 我一开口，它马上知道我在说话 | 说话开始后约 200–400ms 出现 partial 状态/文字 |
| 我说完后不用等很久 | 说话结束后约 600–900ms 提交到 LLM |
| 元亨尽快开口 | LLM 首段文字出来后 100–300ms 内开始合成/播放第一句 |
| 我可以打断它 | 用户连续说话约 200–300ms 内停止当前播放，并取消当前 turn |
| 不会自己把自己吵醒 | 播放中的回声不能连续触发新一轮输入 |
| 连续聊天不需要每次点按钮 | 20 轮连续对话无死锁、无重复提交、无幽灵音频 |
| 不会因为模型暂时失败而整套挂掉 | ASR/TTS/LLM 任一环节失败，都能回到可继续说话状态 |

这些是**第一版工程目标，不是现在已经达到的结果**。每次只改一个环节，必须用固定测试集和真实麦克风各测一次。

---

## 三、当前架构（按实际代码整理）

```text
工作台 assets/webui/console.js
        │ POST /voice + SSE
        ▼
backend/console_server.py::_do_voice
        │
        ├─ tools/tts_test_start._capture_loop
        │      └─ 麦克风 / VAD / 断句
        │
        ├─ backend/target_sherpa_asr.py
        │      └─ partial（主要用于界面显示）
        │
        ├─ SenseVoice（整段 final，当前主要提交来源）
        │      └─ voice_text
        │
        ├─ target_entry / console_turn_stream
        │      └─ 本地 Gemma / 工具 / 记忆
        │
        └─ _StreamingSpeaker
               ├─ Qwen3-TTS 句子级合成
               ├─ sounddevice 播放
               └─ RMS 方式检测插话
```

项目中已经有一条更适合收敛的目标链：

```text
media_adapter.py
  → target_vad.py
  → streaming_asr_bridge.py
  → target_chain.py
  → session_kernel.py / target_runtime.py
  → target_entry.py / target_orchestrator.py
  → tts_provider_port.py
  → target_playback.py
```

**改进原则：不是再新建第三套系统，而是把工作台 `/voice` 迁到第二段目标链。**

---

## 四、目标架构：一个会话、一个 turn owner、两条可替换 Provider

```text
┌────────────────────────────────────────────┐
│                 工作台 / 桌宠 UI             │
│  文本、单句语音、连续语音、停止、插话         │
└─────────────────┬──────────────────────────┘
                  │ SSE/WebSocket 事件
                  ▼
┌────────────────────────────────────────────┐
│ Session Kernel（唯一回合所有者）             │
│ session_id / turn_id / seq / generation     │
│ listening → thinking → speaking → interrupted│
└───────┬───────────────────────┬────────────┘
        │                       │
        ▼                       ▼
┌───────────────┐       ┌────────────────────┐
│ 输入感知层      │       │ 回答输出层          │
│ MediaAdapter   │       │ LLM stream         │
│ VAD + 可选 AEC │       │ sentence buffer    │
│ streaming ASR  │       │ TTS Provider       │
│ partial/final  │       │ Playback Port      │
└──────┬────────┘       └──────────┬─────────┘
       │                           │
       └───────────┬───────────────┘
                   ▼
        事件总线：只接受当前 turn_id
                   │
                   ▼
        Memory / tool / UI / 日志
```

### 必须坚持的四条规则

1. **一个 session 只能有一个活动 turn。**
2. **partial 只能显示，不能写记忆、不能触发工具、不能提交 LLM。**
3. **只有 final 进入正式对话；旧 turn 的任何迟到事件全部丢弃。**
4. **播放、录音、LLM 取消和状态恢复都由 Session Kernel 协调，不能由 UI、ASR 或 TTS 各自维护一份 busy 标记。**

---

## 五、分阶段改进计划

## 阶段 0：先建立基线，不再凭感觉改（半天）

### 目标
知道慢在哪里、错在哪里，先把现状固定下来。

### 要做的事情

1. 新增一个语音 Trace 记录器，例如：
   - `backend/voice_trace.py`
   - `cache/voice_metrics/*.jsonl`
2. 每一轮只记录时间、计数、错误码、状态，不默认保存原始录音或完整转写文本。
3. 每个 turn 至少记录：
   - `capture_open`
   - `speech_start`
   - `first_partial`
   - `speech_end`
   - `asr_final`
   - `llm_start`
   - `llm_first_delta`
   - `tts_first_synth`
   - `playback_start`
   - `barge_in`
   - `playback_stop`
   - `turn_done`
4. 给每一轮分配：
   - `session_id`
   - `turn_id`
   - `generation`
   - `trace_id`
5. 把 `tools/voice_latency_bench.py` 改成能输出 p50/p95，而不是只看平均值。

### 阶段 0 通过条件

- 能够回答“ASR 慢、LLM 慢、TTS 慢还是播放慢”。
- 同一段音频连续跑 5 次，结果中每个阶段都有时间戳。
- 任何异常都有稳定错误码，不只打印 `Exception`。

---

## 阶段 1：把工作台输入链收敛到一套（1–2 天）

### 目标
先不追求更聪明，只解决“我说了但没进入正确回合”的问题。

### 改动顺序

#### 1. 先保留旧 `/voice`，新增一个目标入口

不要一上来删旧代码。新增：

- `POST /voice2`，或
- `/voice?pipeline=target`

这样可以随时 A/B：旧链继续能用，目标链单独验收。

#### 2. 用 `MediaAdapter` 接管麦克风

目标：工作台不再直接依赖 `tools.tts_test_start._capture_loop`。

工作范围：

- `backend/media_adapter.py`
- `backend/target_audio_processor.py`
- `backend/target_vad.py`
- `backend/target_input_resampler.py`

要求：

- 统一为 16kHz、单声道、float32。
- 固定音频块大小，建议先用 20–40ms；不要每个模块自己切块。
- VAD 只输出 `speech_start / speech_frame / speech_end`。
- 输入端带 150–250ms 预滚，避免吞掉第一个字。
- VAD 参数先不凭感觉调整，先用日志和真实麦克风测量。

#### 3. 用 `StreamingASRBridge` 统一 partial/final

工作范围：

- `backend/streaming_asr_bridge.py`
- `backend/target_sherpa_asr.py`
- `backend/asr_provider_port.py`

规则：

- `speech_start` 时打开一个 ASR stream。
- 每个音频块只进入当前 stream。
- partial 发送到 UI：允许显示“正在听……”和暂态文字。
- `speech_end` 时 `finish_stream()` 得到 final。
- final 只提交一次。
- ASR worker 使用有界队列，不能无限堆积。
- 关闭 stream 时必须等待确认，不能启动下一轮后旧线程还在写结果。

#### 4. SenseVoice 改为质量回退，不要每轮主导

第一版建议：

- Sherpa final 作为默认 final。
- 如果 Sherpa final 为空、过短、或低置信度，再用 SenseVoice 做一次整段回退。
- SenseVoice 模型尽量常驻；如果 8GB 资源不允许，就放进独立 worker，并明确“加载一次、连续处理多轮”，不要每轮反复加载/释放。
- fallback 时在 trace 中写明 `asr_route=sherpa` 或 `asr_route=sensevoice_fallback`。

### 阶段 1 通过条件

- 目标入口可以连续说 10 句。
- 每句只有一个 final。
- partial 不会进入记忆、不触发工具、不提前让 LLM 回复。
- 旧 `/voice` 仍可回退。
- 目标链失败时，页面显示明确错误并能重新监听，而不是卡死。

---

## 阶段 2：把“能听见”升级为“能自然接话”（2–3 天）

### 目标
减少等待，让用户感觉是在直接和元亨说话。

### 1. 采用“端点后快速提交”，不要等待过长静音

初始建议：

- 最短有效语音：约 250–350ms。
- 结束静音：先从 450–650ms 测试。
- 最大单轮：约 12–20 秒。
- 如果用户还没说完，不能因为短暂停顿就过早提交。

不要把固定 `duration=3` 当成自然对话的端点检测。连续对话必须由 VAD 状态决定结束。

### 2. 做“预热式提交”，但不能污染正式状态

当 partial 连续稳定一段时间后，可以做两件事：

- 预先检索相关记忆摘要。
- 预先计算本轮可能需要的 prompt 前缀。

但不能：

- 用 partial 直接写入正式会话。
- 用 partial 触发工具。
- 用 partial 产生正式回答。

这样可以把记忆检索和 LLM 前置准备隐藏到用户说话时间里。

### 3. 统一取消与插话

当播放中检测到用户讲话：

1. 立即向 Playback Port 发 `stop`。
2. Session Kernel 将当前 turn 标为 `interrupted`。
3. 取消当前 LLM/TTS 的剩余输出。
4. 清空旧 turn 的 TTS 队列。
5. 增加 generation。
6. 新的输入只进入新 turn。
7. 等播放停止确认后，才允许新 turn 正式开始。

这是防止“你已经说下一句了，但旧答案还在后台继续播”的关键。

### 阶段 2 通过条件

- 连续 20 轮无重复回答。
- 插话 10 次，至少 9 次在 300ms 左右停止旧音频。
- 旧 turn 的迟到 delta 不会出现在新 turn 的 UI 或声音里。
- 说“停”“等等”“不是这个意思”时，系统能优先停止输出。

---

## 阶段 3：重做播放和回声控制（1–2 天）

### 目标
让“可插话”是真的，而不是依赖音量猜测。

### 当前 `_StreamingSpeaker` 的问题

- 每句使用 `sd.play()`，播放控制是全局式的。
- 插话时检测到声音后，退出循环，但必须保证当前音频真的停止。
- 输入只看 RMS，没有 AEC 或回声参考。
- 播放结束、停止确认、音频设备异常没有统一事件。

### 改法

1. 优先使用 `backend/target_playback.py` 的 `SoundDevicePlaybackPort`，不要继续扩展 `_StreamingSpeaker`。
2. 播放输出改为单一 owner 的 OutputStream/队列。
3. 每个音频块都带 `turn_id` 和播放状态。
4. 终止时必须做到：
   - 停止队列继续取数。
   - 调用底层 stop。
   - 等待 `playback_stopped`。
   - 再向 Kernel 报告中断完成。
5. 回声控制按难度分三级：
   - 第一级：播放期间降低 VAD 灵敏度 + 记录播放参考能量。
   - 第二级：加入 `backend/target_noise_suppression.py` 的噪声/回声处理端口。
   - 第三级：如果设备和驱动支持，再接真正的 AEC；不要先写一个没有验证的“伪 AEC”。
6. 麦克风与扬声器尽量使用耳机做第一轮验收。耳机不是最终体验，但能先把状态机问题和声学问题分开。

### 阶段 3 通过条件

- 耳机模式下插话稳定。
- 外放模式下有清晰的“可能是回声”日志，而不是随机触发。
- 播放停止后 1 秒内不会残留旧音频。
- 设备拔出/占用时能回到文本模式或提示重新选择设备。

---

## 阶段 4：优化回答的“直接感”（2–4 天）

### 目标
不改变模型本身，先让回答更像人在交流。

### 1. LLM 流式输出与 TTS 解耦

目标流水线：

```text
LLM token/delta
   → 句子缓冲器
   → 满足条件就提交一小句 TTS
   → 播放队列
```

句子切分规则：

- 遇到 `。！？!?` 可以提交。
- 太长时按逗号/空格/短语切。
- 不要为了等完整答案而积累 200 字。
- 不要把半个词、JSON、工具调用控制符送进 TTS。

当前 `console_server.py` 已有 `_pop_sentence()`，先将它抽成独立模块，再让目标播放端口使用。

### 2. 首句优先，后句可取消

当用户插话时：

- 正在播放的句子立即停。
- 队列中尚未播放的句子全部丢弃。
- LLM 可选择继续生成用于文本显示，也可直接取消；第一版建议直接取消，减少资源竞争。

### 3. 保留文本显示

NEURO 式体验不等于完全不显示文字。建议：

- 用户说话时显示暂态 partial，但用较浅颜色。
- final 后把用户消息固定下来。
- 元亨回答文字继续流式显示。
- 声音可以被打断，但文字答案保留，并标记“已被打断”。

---

## 阶段 5：端到端路线只作为第二 Provider（在阶段 1–4 稳定后）

### 目标
允许你继续试端到端，但不能让实验破坏主链。

新增一个明确的 Provider 接口，例如：

```text
RealtimeVoiceProviderPort
  open_session()
  push_audio(frame)
  receive_events()
  interrupt()
  close()
  health()
```

它必须接入同一个：

- `SessionKernel`
- `turn_id / generation`
- UI SSE/WebSocket 事件
- 取消/打断协议
- 运行指标

端到端 Provider 只允许在以下情况下替换主链：

1. 连续 20 轮不丢句、不重复、不死锁。
2. 首音频延迟不差于混合链太多。
3. 插话和停止行为与主链相同。
4. 失败时可以自动回退到 `StreamingASR + LLM + TTS`。
5. 能够正确接入记忆、工具和会话历史。

**不符合以上条件的端到端模型，只放在 `tools/` 做对照实验，不接入 `console_server.py` 的默认入口。**

---

## 六、建议的文件改动清单

### 第一批：只做观测和统一事件

新增：

- `backend/voice_trace.py`
- `backend/voice_events.py`
- `tools/voice_acceptance.py`
- `tools/voice_metrics_report.py`

修改：

- `backend/session_kernel.py`
- `backend/streaming_asr_bridge.py`
- `backend/target_runtime.py`
- `backend/target_chain.py`

### 第二批：目标链接入工作台

修改：

- `backend/console_server.py`
- `assets/webui/console.js`
- `backend/media_adapter.py`
- `backend/target_vad.py`
- `backend/target_sherpa_asr.py`

原则：新增 `pipeline=target` 的兼容入口，先不删除旧 `/voice`。

### 第三批：播放和插话

优先复用/修改：

- `backend/target_playback.py`
- `backend/tts_provider_port.py`
- `backend/console_server.py` 中的 `_StreamingSpeaker`（最终应缩减为兼容适配器）
- `backend/target_noise_suppression.py`

### 第四批：验收与回归

新增/修改：

- `backend/test_target_acceptance.py`
- `backend/test_target_playback.py`
- `backend/test_streaming_asr_bridge.py`
- `backend/test_session_kernel.py`
- `tools/voice_latency_bench.py`
- `tools/realtime_acceptance.py`

---

## 七、每一步怎么判断“可以继续”

### A. 输入层

- [ ] 真实麦克风能连续产生 16kHz 单声道音频块。
- [ ] 第一个字不被吞掉。
- [ ] 说话开始/结束事件不会抖动。
- [ ] 10 句中至少 9 句有 final。
- [ ] 旧 stream 不会继续向新 turn 发事件。

### B. ASR 层

- [ ] partial 只是暂态展示。
- [ ] final 只提交一次。
- [ ] Sherpa 优先，SenseVoice 只在明确条件下回退。
- [ ] 模型不在每轮重复加载。
- [ ] ASR 失败能自动回到 listening。

### C. LLM 层

- [ ] `console_turn_stream()` 每轮只调用一次。
- [ ] 一个 turn 只产生一个正式答案。
- [ ] 取消后不再提交旧回答的后续 delta。
- [ ] 工具调用不会被 partial 触发。

### D. TTS/播放层

- [ ] 首句可以先播。
- [ ] 播放中讲话可以停。
- [ ] 停止后无残留音频。
- [ ] 新 turn 不会播旧队列。
- [ ] TTS 失败时文本仍能显示。

### E. 连续对话层

- [ ] 20 轮连续对话不需要刷新页面。
- [ ] 没说话时不会无限提交空 turn。
- [ ] UI 的 listening/thinking/speaking 状态与 Kernel 一致。
- [ ] 任何异常都会回到 idle 或 listening，不会永久 busy。

---

## 八、建议的测试顺序（不要颠倒）

### 第 1 轮：不用扬声器，只戴耳机

1. 启动本地服务。
2. 打开工作台语音模式。
3. 连续说 10 句短句：问候、数字、否定、打断。
4. 看 `voice_trace` 的四个时间：speech start、final、first delta、playback start。
5. 只改输入端，不改人格、不改记忆、不换模型。

### 第 2 轮：测试插话

1. 让元亨回答稍长的问题。
2. 在第一句播放中说“停”。
3. 立刻说下一句。
4. 检查旧答案声音是否停止、新问题是否只生成一个 turn。

### 第 3 轮：外放测试

1. 先把音量调低。
2. 只测试“元亨回答时我不说话”是否会误触发。
3. 再测试插话。
4. 最后才调 VAD 阈值和回声参数。

### 第 4 轮：端到端 A/B

同一批固定音频分别跑：

- A：目标混合链：Sherpa → Gemma → Qwen TTS。
- B：音频直入实验链。

比较：

- 是否听懂。
- 首个回答延迟。
- 是否能取消。
- 是否能连续 20 轮。
- 是否能进入记忆和工具系统。

**谁的体验更稳定，谁才是主链；不是谁“看起来更端到端”，谁就赢。**

---

## 九、出现问题时怎么排查

| 现象 | 第一检查点 | 不要先做的事 |
|---|---|---|
| 一直听不到 | `MediaAdapter`、采样率、设备号、VAD 事件 | 不要先换 LLM |
| partial 有，final 没有 | `StreamingASRBridge.finish_stream()` 和 stop 顺序 | 不要先改提示词 |
| final 正确但回答慢 | `llm_first_delta`、模型服务端口 8081 | 不要先换 ASR |
| 回答文字快，声音慢 | TTS 首句合成和播放队列 | 不要先做纯端到端 |
| 元亨自己打断自己 | 播放参考、AEC、耳机对照 | 不要只提高 RMS 阈值 |
| 插话后旧声音还在 | `target_playback.py` 的 stop/wait_stopped | 不要在 UI 再加一个 stop flag |
| 连续几句后卡死 | Session Kernel turn/generation、旧 worker 是否退出 | 不要重新启动整个 daemon |
| 端到端模型偶尔听懂 | 固定测试集和连续 20 轮验收 | 不要直接设成默认路线 |

---

## 十、你现在最先做的三件事

### 第一步：不要再开第三套链路

先把当前工作台 `/voice` 的真实路径画清楚，并给它加 trace。目标是确认：

```text
capture_loop → Sherpa partial → SenseVoice final → console_turn_stream → _StreamingSpeaker
```

### 第二步：新增 `pipeline=target`，不要直接改掉旧入口

把已经存在的：

```text
MediaAdapter + TargetVADProvider + StreamingASRBridge + SessionKernel + TargetPlayback
```

接成一条能跑的最小目标链，先完成“单句说话 → final → 文本回答”，再接 TTS，再接连续模式。

### 第三步：先用耳机完成插话验收

耳机模式下做到：

- 我说话能被识别。
- 元亨能开始回答。
- 我说“停”能在约 300ms 内停止声音。
- 下一句不会混入上一句。

这四件事完成后，再处理外放回声和真正端到端模型。

---

## 十一、最终交付定义

当以下条件全部满足时，才认为“NEURO 式直接对话第一版完成”：

1. 工作台默认可以进入连续语音模式。
2. 不需要每轮手动点击开始/停止。
3. partial、final、LLM、TTS、播放都属于同一个 session/turn 协议。
4. 说完后约 1 秒左右开始听到第一句回答（以本机实际 trace 为准）。
5. 用户可以自然插话，旧回答会停止。
6. 20 轮连续对话无卡死、无重复、无幽灵音频。
7. ASR、TTS、LLM 任一环节失败时有降级路径。
8. 端到端实验可以随时切换，但不会破坏稳定混合链。
9. 每次改动都有固定测试结果，而不是只凭“这次感觉好像更快”。

**一句话总结：你现在不缺模型，缺的是把已有的目标语音架构真正接到工作台，并让一个 Session Kernel 管住收音、思考、播放和插话。先把这条链做成，再谈端到端。**

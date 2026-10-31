# YHLZ 对话链路收口实施方案（基于现有架构）

**版本**：v1.0  
**日期**：2026-09-27  
**项目目录**：`C:\Users\ACE_WAN——PROJECT\YHLZ`  
**本方案目的**：不再继续堆第三套语音链，先把现有“能收音、能识别、能回答、能播音”的零散能力收成一条真正可连续对话、可插话、可观测、可回退的主链。

---

## 0. 先给结论：现在真正要解决的不是“换哪个模型”，而是“谁负责一轮对话”

当前系统已经有足够多的零件：

- 工作台旧入口：`backend/console_server.py` 的 `/voice`；
- Sherpa partial / SenseVoice final；
- Gemma 对话；
- Qwen3-TTS；
- `MediaAdapter`、`StreamingASRBridge`、`SessionKernel`、`TargetPlayback` 等目标架构；
- `voice_dialog_probe.py`、`voice_latency_bench.py` 等测试工具。

但现在的问题是：这些零件没有由一个统一的“回合协调者”管理。结果就是：

1. 旧 `/voice` 和目标链各走各的；
2. partial、final、音频直入可能同时触发处理；
3. 一句话可能被 ASR、LLM 或转写逻辑重复处理；
4. TTS 正在播放时，新一句话无法干净取消旧一句；
5. 看起来像“端到端慢”，实际上是多个等待、重复加载和队列残留叠加。

### 最终主链

```text
麦克风
  → MediaAdapter / VAD
  → StreamingASRBridge
  → Sherpa partial（只显示）
  → Sherpa final（只提交一次）
  → DialogueCoordinator / SessionKernel
  → ConversationSession.run_turn(text)
  → LLM 流式 delta
  → SentenceBuffer
  → Qwen3-TTS
  → TargetPlayback
  → 播放中检测插话
  → 取消旧 turn，开始新 turn
```

**注意：第一版不把“纯音频直入的端到端模型”当默认主链。** 先把这条混合流式链跑稳，用户体验已经可以接近 NEURO；端到端模型以后只作为可替换 Provider 做 A/B。

---

## 1. 遗留清点：哪些代码保留、哪些代码降级、哪些代码不再当主链

| 模块 | 当前角色 | 收口后的角色 | 处理原则 |
|---|---|---|---|
| `backend/console_server.py::_do_voice` | 工作台旧语音总入口 | 兼容入口 / 回退入口 | 暂时保留，不继续往里面堆功能 |
| `tools/tts_test_start._capture_loop` | 旧式收音和处理 | 仅用于旧模式或对照测试 | 不作为新主链 |
| `backend/streaming_asr_bridge.py` | partial/final 桥 | 新输入主链 | 负责生命周期、flush、final 唯一性 |
| `backend/target_sherpa_asr.py` | Sherpa 实现 | 主 ASR Provider | 模型常驻，不能每轮重新加载 |
| SenseVoice | 整段 final | 质量回退 | 只在 Sherpa final 为空/异常时调用 |
| `backend/session_kernel.py` | 目标会话骨架 | 唯一 turn owner | 管 session、turn、generation、取消、状态 |
| `ConversationSession` | 对话与记忆 | 正式 LLM 会话核心 | 一轮只提交一次正式文本 |
| `_transcribe_audio_turn()` | 后台音频二次转写 | 默认关闭 | 禁止同一音频再次调用 LLM 转写 |
| `_StreamingSpeaker` | 旧 TTS/播放 | 兼容实现 | 目标链稳定后不再作为默认播放器 |
| `backend/target_playback.py` | 目标播放 | 默认播放出口 | 所有声音必须带 turn/generation |
| `tools/voice_dialog_probe.py` | 实验/基准 | 回归测试工具 | 不直接替代工作台主链 |
| 音频直入 / audio-direct | 端到端实验 | 第二 Provider | 只做 A/B，不直接接管记忆与工具 |

### 明确废止的行为

- partial 触发正式 LLM、记忆写入或工具调用；
- Sherpa、SenseVoice、音频直入同时作为正式结果；
- 每一轮重新加载 ASR/TTS 模型；
- 用前端一个 `stop` 标志代替后端取消；
- 旧 turn 的迟到事件继续写入新 turn；
- 在没有固定测试集的情况下切换默认链。

---

## 2. 统一协议：先把“对话回合”定义清楚

### 2.1 一个 session，很多 turn

```text
session_id：一次连续打开语音对话的会话
turn_id：用户一次发言及其回答
generation：每次取消/插话后递增，用来淘汰旧事件
```

每一个异步事件至少带：

```json
{
  "session_id": "s-xxx",
  "turn_id": 12,
  "generation": 8,
  "event": "asr_final|llm_delta|tts_start|playback_stop|error",
  "ts_mono_ms": 123456.7
}
```

消费方必须执行：

```text
如果事件的 generation 不是当前 generation：直接丢弃
如果事件的 turn_id 不是当前 turn：不能产生声音、不能写记忆
```

### 2.2 状态机

```text
IDLE
  → LISTENING
  → CAPTURING
  → FINALIZING_ASR
  → THINKING
  → SPEAKING
  → LISTENING
```

任意状态都可以进入：

```text
CANCELLING → LISTENING 或 IDLE
ERROR      → LISTENING 或 IDLE
```

插话必须是后端状态迁移，而不是只改 UI：

```text
SPEAKING
  → 检测到用户有效语音
  → generation += 1
  → cancel LLM
  → 清空 TTS 队列
  → TargetPlayback.stop_and_wait()
  → 新 turn 开始
```

### 2.3 事件分层

- `asr_partial`：只能更新字幕；
- `asr_final`：一次性提交给对话协调层；
- `llm_delta`：只进入回答缓冲区；
- `sentence_ready`：达到句号、问号、感叹号或长度阈值才送 TTS；
- `tts_audio`：带 turn/generation；
- `playback_started/stopped`：更新状态；
- `error`：必须让链路回到可用状态。

---

## 3. 分阶段实施计划

## 阶段 0：做基线和 trace（半天，先不要改模型）

### 目标

回答清楚“慢到底慢在哪里”，不要再靠感觉判断。

### 需要记录的时间点

```text
capture_start
first_audio_frame
first_asr_partial
asr_final
llm_request
llm_first_delta
sentence_ready
tts_request
tts_first_audio
playback_start
playback_stop
turn_done
```

每轮计算：

```text
端点等待 = asr_final - 最后一次有效语音
ASR 延迟 = asr_final - capture_start
LLM 首字延迟 = llm_first_delta - asr_final
TTS 首包延迟 = tts_first_audio - sentence_ready
播放首声延迟 = playback_start - tts_first_audio
总首声延迟 = playback_start - 用户停止说话
```

### 阶段 0 通过条件

至少采集：

- 10 句短句；
- 10 句长句；
- 5 次停顿后继续说；
- 5 次回答中插话。

没有 trace 的改动一律不进入主链。

---

## 阶段 1：先统一“输入 → 正式文本”（1–2 天）

### 改动顺序

1. 新增或整理 `backend/dialogue_coordinator.py`，先不删除旧代码；
2. 工作台增加 `pipeline=target` 路由；
3. `MediaAdapter` 负责麦克风生命周期；
4. `StreamingASRBridge` 负责 partial/final；
5. Sherpa final 作为主结果；
6. SenseVoice 只做 fallback；
7. final 进入 `DialogueCoordinator`，只允许提交一次；
8. 文字模式也走同一个 `DialogueCoordinator`，这样先验证对话核心。

### 这里必须修掉的两个延迟源

#### 端点延迟

现在约 100ms 一个 block，连续 6 个静音 block 才结束，约等于 600ms 的固定等待。改成配置项：

```text
endpoint_silence_ms = 450 / 500 / 600
```

先用 500ms 做基线，再用固定语音集比较“漏尾”和延迟。不能盲目降到 200ms，否则会把一句话截断。

#### 重复转写

正式主链二选一：

- 路线 A（推荐）：Sherpa final → 文本 → LLM；音频只作为可选证据；
- 路线 B（实验）：音频 → 端到端模型；关闭后台 `_transcribe_audio_turn()`。

两条不能同时作为正式逻辑。

### 阶段 1 通过条件

- 语音 10 句至少 9 句有 final；
- partial 不进入记忆、不触发工具；
- final 每轮只提交一次；
- ASR 模型不在每轮重新加载；
- 同一段音频不会被 LLM 转写两次；
- 任意 ASR 异常都能回到 `LISTENING`。

---

## 阶段 2：统一“文本 → 回答 → 首句声音”（2–3 天）

### LLM 侧

正式回答走现有：

```text
ConversationSession.run_turn(text)
  → target_daemon.console_turn_stream
  → target_orchestrator / llm_stream
```

但要分两种模式：

- **Fast Path**：短历史、无工具或极少工具、关闭 reasoning、回答上限约 200–400 token；
- **Task Path**：需要工具、长上下文、记忆检索或复杂任务时再走完整链路。

语音闲聊默认 Fast Path。复杂任务可以慢，但必须让 UI 明确显示 `thinking`，不能让整套工具和历史默认拖慢每一句闲聊。

### TTS 侧

实现：

```text
LLM delta
  → SentenceBuffer
  → 达到首句阈值
  → TTS
  → TargetPlayback
```

首句触发建议：

- 遇到 `。！？`；或
- 累积 18–35 个汉字；或
- LLM 结束；

不要等待完整回答后才 TTS。

### 阶段 2 通过条件

- `asr_final → llm_first_delta` 可观测；
- `sentence_ready → playback_start` 可观测；
- 首句播放时，后续句子仍可继续生成；
- 取消后，旧 LLM 不再产生新的 TTS 音频；
- TTS 失败时，文字回答仍完整显示。

---

## 阶段 3：做真正的插话和播放收口（1–2 天）

### 插话流程

```text
播放中
  → 输入 VAD 检测到连续有效语音
  → 忽略极短噪声
  → 停止播放
  → 取消当前 LLM/TTS
  → generation += 1
  → 清空旧音频队列
  → 新语音继续 ASR
```

### 先用耳机验收

外放会产生回声，不能一开始就用外放判断 ASR。耳机模式下先做到：

- 说“停”后约 300ms 左右停止旧声音；
- 下一句只生成一个新回答；
- 旧回答不再幽灵式播出；
- 20 轮内没有卡在 `speaking`。

### 外放再处理

耳机验收通过后再处理：

- 播放参考信号；
- AEC 或至少播放期间的输入抑制；
- VAD 阈值；
- 说话人/回声区分。

不要只把 RMS 阈值调大，这会让用户声音也被吞掉。

---

## 阶段 4：端到端只做第二 Provider（稳定后再做）

### 端到端低延迟吗？

不天然低延迟。端到端只有在下面条件同时成立时，才可能比当前链路更快：

- 模型支持真正的实时输入帧，而不是等完整 WAV/base64；
- 支持增量输出，而不是等完整回答；
- 首包音频生成很快；
- 推理线程没有和 ASR、LLM、TTS 抢同一块显存；
- 端点策略、网络、播放设备不成为新瓶颈。

如果当前 audio-direct 是“录完一段 WAV，再一次性提交”，那只是把 ASR 步骤藏起来，不是实时端到端。

### 是否需要训练？

**现阶段不需要训练。** 先解决工程瓶颈：

- 端点等待；
- 模型重复加载；
- ASR 双处理；
- LLM 首 token；
- TTS 首包；
- 播放队列与取消；
- GPU/CPU 竞争。

只有当 trace 证明“速度已经够了，但识别专有词、口音或人格稳定性不行”时，才考虑针对性训练。训练不能替代取消、队列和状态机。

### 端到端 A/B 的准入条件

端到端 Provider 必须实现同一套接口：

```text
start_turn()
send_audio_frame()
finish_input()
on_partial()
on_final()
on_audio()
cancel()
```

它必须通过与混合链相同的验收：

- 20 轮连续对话；
- 10 次插话；
- 记忆/工具不重复触发；
- 旧 turn 不出声；
- provider 失败可回退到混合链。

---

## 4. 建议的文件改动顺序

### 第一批：只做观测和接口，不改默认链

- `backend/dialogue_coordinator.py`：新增；
- `backend/session_kernel.py`：补齐 turn/generation/cancel；
- `backend/console_server.py`：增加 trace 和 `pipeline=target`；
- `tools/voice_latency_bench.py`：输出 p50/p95；
- `tools/voice_dialog_probe.py`：固定测试样本与回放。

### 第二批：接输入主链

- `backend/streaming_asr_bridge.py`：明确 partial/final 生命周期；
- `backend/target_sherpa_asr.py`：模型常驻与异常恢复；
- `backend/target_entry.py`：正式走 transcript，关闭默认后台二次转写；
- `backend/target_daemon.py`：统一转发事件。

### 第三批：接播放和插话

- `backend/target_playback.py`：补 `stop_and_wait()`、队列清空和 generation 检查；
- `backend/target_runtime.py`：把 TTS 句子流绑定到当前 turn；
- `assets/webui/console.js`：只消费状态事件，不自行管理取消真相。

### 第四批：验收和回归

- 新增固定 20 轮文字回归；
- 新增固定 10 句语音回归；
- 新增 10 次插话回归；
- 记录 p50/p95，不只看平均值；
- 通过后再考虑切换默认 `/voice`。

---

## 5. 验收指标：达到这些才算“对话链路完成”

### 最小可交付版本

1. 连续模式无需每轮点击开始/停止；
2. 文字 20 轮无重复、无死锁；
3. 语音 10 句至少 9 句有 final；
4. partial 从不触发正式回答、记忆或工具；
5. final → LLM 只提交一次；
6. 第一小句能先播，不等整段回答；
7. 播放时讲话可以停止旧回答；
8. 停止后旧队列不会继续出声；
9. ASR/LLM/TTS 任一失败能回到 listening/idle；
10. 端到端 Provider 可以切换，但失败能回到混合链。

### 延迟目标（先作为方向，不要拿来掩盖识别错误）

```text
说完 → final：p50 ≤ 700ms，p95 ≤ 1200ms
final → LLM 首 delta：p50 ≤ 1200ms，p95 ≤ 2500ms
首句就绪 → 播放开始：p50 ≤ 800ms，p95 ≤ 1500ms
插话 → 旧播放停止：p50 ≤ 300ms，p95 ≤ 600ms
```

如果达不到，必须从 trace 指定是哪一段不达标，不能泛泛地说“端到端不行”。

---

## 6. 现在立刻执行的三件事

### 第 1 件：冻结架构

今天不再新增第三套语音链，也不训练端到端。把旧 `/voice` 标成兼容链，把目标链标成开发主链。

### 第 2 件：先接 `DialogueCoordinator`

不要先换模型。先保证：

```text
文本输入 → 唯一 turn → LLM 流式输出 → 句子级 TTS → 可取消
```

文字链跑通后，再把 final transcript 接进来。这样可以把 ASR 问题与对话问题分开。

### 第 3 件：用耳机完成插话验收

验收通过后，才处理外放回声；外放通过后，才做端到端 A/B；A/B 通过后，才讨论训练。

---

## 7. 最终决策

这次项目的主线不是“再找一个更神奇的模型”，而是：

> **用一个 SessionKernel/DialogueCoordinator 管住一次对话的所有生命周期；用 Sherpa 做低延迟输入，用 Gemma 做流式理解，用 Qwen3-TTS 做句子级输出，用 TargetPlayback 做可取消播放；端到端只作为可替换实验，不再让它绕过会话、记忆、工具和取消机制。**

这样做的好处是：

- 你今天就能开始改，不需要等训练；
- 每一步都有明确验收；
- 旧链不会被一次性删掉；
- 端到端如果真的更好，可以替换 Provider；
- 如果端到端不稳定，也不会拖垮已经稳定的对话主链。

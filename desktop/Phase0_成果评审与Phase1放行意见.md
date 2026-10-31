# Phase 0 成果评审与 Phase 1 放行意见

**评审日期**：2026-09-27  
**评审对象**：`方案成果/Phase0_埋点观测_20260927.md`、commit `48bc6bf`  
**评审结论**：**Phase 0 的代码盘点和埋点骨架通过；真机基线尚未完成，因此暂不放行 Phase 1 管线切换。**

---

## 一、这批成果做对了什么

### 1. 先做观测，没有先改业务链
这是正确顺序。当前最危险的是凭感觉换 ASR、换端到端模型、换 TTS，最后不知道哪一段变慢。`voice_trace.py` 和少量 `console_server.py` 埋点让后续可以看到阶段时间。

### 2. 代码盘点确认了最重要的事实
当前确实是两条管线并存：

```text
Live /voice：麦克风 → RNNoise/VoiceFrontend → Sherpa/SenseVoice → LLM → _StreamingSpeaker
Target：MediaAdapter → StreamingASRBridge → TargetVoiceChain → SoundDevicePlaybackPort
```

并且 Target 链当前没有接入 `/voice`。这意味着下一步不能直接说“Target 链已经是主链”，必须单独接线和验收。

### 3. 发现了真实 API 差异
`target_playback.py` 没有方案中曾经写的 `stop_and_wait()`，实际是 `wait_stopped(timeout_s)`。这类差异如果不提前查出来，Phase 1 会在接口层直接卡住。

### 4. 发现 8GB 显存约束
SenseVoice 与 TTS 不能稳定同时驻留，`release_sv()` 会影响真实延迟。后续报告必须把“模型释放/重新加载”单独记出来，不能把它混在普通 ASR 延迟里。

---

## 二、当前不能直接称为“基线已完成”的原因

成果文档写的是“埋点已完成、待真机测试”，这个判断是对的。现在只能说：

> **埋点骨架验证完成，真实延迟基线尚未完成。**

原因不是挑剔，而是目前记录的数据还不够覆盖方案里的五个关键指标。

### 问题 1：一个 `/voice` 请求只有一个 VoiceTrace
`_do_voice()` 在进入循环前创建一次：

```python
vt = VoiceTrace(session_id="console", turn_id=0)
```

连续模式里只是反复修改：

```python
vt.turn_id = rounds
```

最后在整个请求结束时才 `flush()`。所以连续模式的 20 轮会被写成一个 JSONL 记录，而不是 20 个 turn 记录。这样会导致：

- 一个 record 中有多个 `capture_start`、`asr_final`、`llm_first_delta`；
- `latency_report()` 用 `next(...)` 取第一条事件，可能把第 1 轮的开始和第 1 轮之后的事件配错；
- `turn_id` 最后会变成 20，前面事件看不出属于哪一轮；
- 无法准确得到每轮 p50/p95。

**Phase 1 前必须修正：**每一轮循环创建一个 `VoiceTrace(session_id, turn_id=rounds, generation=...)`，每轮 `finally` 单独 flush；请求结束只保留 session 汇总，不把多轮混在一个 record 里。

### 问题 2：报告定义了 13 个事件，实际只覆盖一部分
当前 `/voice` 实际埋到的主要是：

```text
capture_start
speech_end
asr_final
llm_start
llm_first_delta
sentence_ready
turn_done
```

但报告的关键指标依赖这些尚未真正埋到的事件：

```text
speech_start
first_partial
tts_first_synth
playback_start
barge_in
playback_stop
```

所以现在还不能计算：

- 真实“用户开始说话 → final”；
- 句子就绪 → 实际开始播放；
- 插话发生 → 实际停止播放。

**建议：**在真机基线前先把事件补齐；如果暂时不能补齐，就把报告名称改成已经真实存在的指标，不要用不存在的事件给出结论。

### 问题 3：`speech_end` 不等于 `speech_start`
当前代码在 `_listen()` 返回后标的是 `speech_end`，但 `latency_report()` 计算的是：

```text
speech_start → asr_final
```

当前没有 `speech_start`，因此“说话→final”这个指标实际上不会有数据。应在 VAD 第一次确认有效语音时记录 `speech_start`，而不是用收音循环的 `capture_start` 冒充。

### 问题 4：TTS/播放时间还没有真实证据
`sentence_ready` 只表示文本句子准备好了，不表示：

- TTS 开始合成；
- 第一段音频合成完成；
- sounddevice 真正开始播放。

必须在 `_StreamingSpeaker` 或其底层 TTS/playback 回调中补：

```text
tts_start
tts_first_synth
playback_start
playback_stop
```

否则只能知道“文本什么时候准备好”，不知道用户什么时候真的听到声音。

### 问题 5：插话指标还没有埋
目前已有 RMS 门控和取消逻辑，但没有把两个时刻写入 trace：

```text
barge_in：确认是用户语音的时刻
playback_stop：播放设备确认停止的时刻
```

`barge_in → playback_stop` 是本项目最关键的体验指标之一，不能只看 `_tc.cancelled` 或前端状态。

### 问题 6：连续模式与并发安全
`VoiceTrace` 的注释写“Thread-safe via GIL”，但它没有显式锁，而 partial/LLM/TTS 事件可能来自不同线程。CPython 下 list append 通常不会损坏，但这不是完整的线程安全协议。建议加 `threading.Lock`，并在读取事件、`latency()`、`to_dict()`、`flush()` 时使用同一把锁。

### 问题 7：落盘文件名可能覆盖
现在文件名主要由秒级时间、session_id、turn_id 组成：

```text
YYYYMMDD_HHMMSS_console_1.jsonl
```

同一秒内重复请求或相同 turn 可能覆盖文件。建议文件名加入 `trace_id` 或毫秒/UUID，例如：

```text
20260927_195034_console_1_trace_xxx.jsonl
```

### 问题 8：p95 算法是简化版
`latency_report()` 当前通过排序索引取 p50/p95，适合粗看，但不是严格百分位算法，且小样本的 p95 可能等于最大值。Phase 0 可以保留，但输出必须带 `count`，真机至少采集 20 轮后再判断。不要用 1–3 轮数据宣布优化有效。

---

## 三、批准和暂缓项

### 现在批准

- 保留 `voice_trace.py` 作为观测基础；
- 继续只做埋点补齐，不改 ASR/LLM/TTS 行为；
- 在耳机模式下跑固定语音回放和连续对话；
- 采集至少 20 个独立 turn；
- 输出每一项指标的 count、p50、p95、min、max 以及缺失事件数。

### 现在暂缓

- 不切换 `pipeline=target` 默认入口；
- 不删除旧 `/voice`；
- 不做端到端模型 A/B；
- 不训练；
- 不把当前 7 个事件的结果当作完整延迟基线；
- 不用“埋点代码通过”代替“真机链路通过”。

---

## 四、下一步给工作 Agent 的明确任务

### P0：修正 trace 生命周期

目标：每个 turn 一个 JSONL。

验收：连续 5 轮后得到 5 个独立记录，每条的 `turn_id` 唯一，`events` 不混入其他轮。

### P1：补齐可计算事件

最低补齐：

```text
speech_start
first_partial
tts_start 或 tts_first_synth
playback_start
barge_in
playback_stop
```

验收：`latency_report()` 五个指标中，至少四个有真实 count；插话指标没有事件时必须明确显示 count=0，不能伪造。

### P2：跑真机基线

测试顺序：

1. 耳机模式 10 句短句；
2. 耳机模式 10 句长句；
3. 连续 20 轮；
4. 播放中插话 10 次；
5. 最后才测外放和回声。

产物必须包括：

- 原始 JSONL；
- 汇总报告；
- 缺失事件统计；
- 失败样本文本和错误日志；
- 运行时模型/设备配置。

### P3：Phase 1 放行条件

全部满足才进入 Target 接入：

- 每轮 trace 独立；
- 20 轮数据可复现；
- final 只提交一次；
- 真实播放和插话停止可观测；
- 能明确指出当前最大延迟段；
- 旧 `/voice` 在基线期间没有被破坏。

---

## 五、最终评语

这批成果方向正确，**Phase 0 代码骨架可以验收，但“观测闭环”还没完成**。最关键的不是马上改模型，而是先把 trace 从“记录几个事件”升级成“每轮可配对、可计算、能证明用户何时听到声音”的证据链。

一句话：

> **Phase 0 先判定为“部分通过：埋点框架通过，真机基线和事件完整性待补”；Phase 1 先不切换，先修 trace 生命周期并跑出 20 轮真实数据。**

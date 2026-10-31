# Phase 1.5：台账已核验、真机准备与 Target 适配器下一步执行单

**更新时间**：2026-09-28 14:05（Asia/Shanghai）  
**项目**：`C:\Users\ACE_WAN——PROJECT\YHLZ`  
**交付目录**：`C:\Users\ACE_WAN——PROJECT\Desktop\方案建议\方案成果`

> 这份执行单是“现在能证明什么、还不能证明什么、下一步按什么顺序做”的操作版说明。不要把“代码存在”当成“真机已经通过”。

---

## 1. 先给结论

### 1.1 台账修复：已经通过真实 MCP 验证

我没有直接读取台账文件，而是启动项目自带的 `yhlz` stdio MCP 服务，通过 `ledger_search` 和 `system_time` 实际调用：

- MCP server：`yhlz`
- 工具列表包含：`ledger_search`、`memory_recall`、`system_time` 等
- 当前时间核验：2026-09-28 14:05（Asia/Shanghai）
- 关键记录：
  - `ledger:0510:6436-6441`：Phase 0 埋点评审；结论是代码/埋点骨架通过，但真机基线未完成，Phase 1 暂不放行。
  - `ledger:0510:6439`：现有埋点仍缺完整的 speech_start、first_partial、TTS 首合成、播放开始、插话停止证据。
  - `ledger:0510:6440`：先修 trace 生命周期，再做耳机至少 20 轮和 10 次插话；不切默认链、不训练、不做端到端 A/B。
  - `ledger:0155:2260-2564`：全双工先走“耳机 + 唤醒词”路线，外放 AEC 后置。

所以，**台账索引修复已经不是猜测，MCP 检索链路已恢复可用**。但目前项目的 MCP server 没有 `ledger_append` 工具，本轮不伪造“已追加台账记录”；本执行单和测试产物记录了本轮结果，正式台账追加需要后续提供专用写工具或按项目约定处理。

### 1.2 Python/依赖：已确认可运行，不需要重建虚拟环境

以下已经用项目虚拟环境实际运行：

```powershell
cd C:\Users\ACE_WAN——PROJECT\YHLZ
.\.venv\Scripts\python.exe --version
```

结果：Python 3.12.10。之前出现的 `Unable to create process ... ??PROJECT` 是权限/启动上下文问题，不是 venv 损坏。**不要重装依赖、不要重建 venv。**

### 1.3 软件预检：通过；耳机真机：尚未确认

预检报告：

```text
cache/voice_metrics/real_machine_preflight.json
```

已确认：

- numpy、sounddevice、soundfile 存在；
- sherpa_onnx、torch、faster_qwen3_tts 可发现；
- Target 相关 backend 模块可发现；
- sounddevice 可以枚举输入和输出设备；
- metrics 目录真实写入探测通过；
- 没有开启麦克风流，没有播放声音，没有加载模型。

本机设备枚举结果：

- 输入候选：设备 1，`麦克风阵列 (Realtek(R) Audio)`，44100 Hz；
- 当前默认输出：设备 3，`扬声器 (Realtek(R) Audio)`，44100 Hz；
- 耳机候选：设备 11，`Headphones (Realtek HD Audio 2nd output)`，44100 Hz。

**设备枚举不等于耳机已插好，也不等于声音实际从耳机出来。** 因此报告中 `software_preflight_passed=true`，但 `ready_for_supervised_headset_bench=false`，必须人工确认耳机后才能开流。

---

## 2. 本轮已经做的代码工作

### 2.1 TargetWorkbenchAdapter：解决“工作台接 Target，但不再造第二套系统”

新增/完善：

- `backend/target_workbench_adapter.py`
- `backend/test_target_workbench_adapter.py`

适配器的职责只有边界转换，不拥有业务状态：

```text
工作台 JSON
  ↓ normalize_request()
显式 pipeline=target 才允许进入 Target
  ↓
TargetWorkbenchAdapter
  ↓
已有 TargetVoiceChain
  ↓
已有 SessionKernel / turn / generation / cancellation
  ↓
已有 TTS Provider / Playback
```

适配器明确不创建：

- 第二个 `SessionKernel`；
- 第二个 `TargetVoiceChain`；
- 第二套 turn/generation；
- 第二份播放队列；
- 第二份历史、记忆或取消状态。

默认请求仍然安全地走旧链：

```json
{"pipeline":"legacy"}
```

只有工作台明确选择才进入 Target：

```json
{
  "pipeline": "target",
  "continuous": true,
  "audio_route": "headset"
}
```

注意：**适配器目前已经有契约和生命周期测试，但还没有接入 HTTP `/voice` 默认入口。** 所以不能说“HTTP 已经可以通过 pipeline=target 自动切换”；接线是下一步开发，不是本轮已完成事实。

### 2.2 适配器的安全修正

本轮还处理了 5 个容易造成幽灵问题的边界：

1. **runtime 必须共享同一个 chain**：传入不同 chain 会直接拒绝，防止媒体输入和文本提交分裂成两条链。
2. **未 start 时 ingest 必须返回 false**：适配器不自己维护第二份状态机，真实状态由 `TargetVoiceRuntime` 决定。
3. **等待结果使用 `asyncio.shield`**：调用者取消等待，不会误取消 chain 持有的 turn task；真正的 stop/interrupt 必须显式调用 chain 的接口。
4. **事件 sink 只接受同步函数**：避免异步 sink coroutine 被创建后直接关闭、事件静默丢失。
5. **telemetry 脱敏**：文本、音频、token、authorization 和未知对象不进入事件；异常统一返回 `TARGET-ADAPTER-ERROR`，不把 provider 异常文本或密钥片段写入日志。

插话的事件也不再无条件伪造 `interrupted`：如果 chain 返回 timeout/failed evidence，事件只标记为返回结果和失败状态，不能把“请求取消”冒充“声卡已经停止”。

### 2.3 真机预检工具的边界修正

`tools/voice_real_machine_preflight.py` 现在：

- 直接运行脚本时会把项目根目录加入 `sys.path`，不会再误报 backend 模块缺失；
- 真正创建临时文件验证 metrics 目录可写，不再用“目录存在”代替写权限；
- 自动列出耳机候选，但不宣称耳机已插入；
- 明确输出“软件预检通过”和“人工耳机确认”两个不同结论；
- 不打开音频流、不加载模型、不自动播放。

---

## 3. 已实际执行的验证

### 3.1 回归测试

```powershell
.\.venv\Scripts\python.exe -m unittest `
  backend.test_voice_trace `
  backend.test_voice_real_machine_preflight `
  backend.test_target_workbench_adapter `
  backend.test_target_chain `
  backend.test_target_runtime `
  backend.test_streaming_asr_bridge `
  backend.test_target_playback `
  backend.test_target_composition -q
```

结果：**84 tests，全部 OK**。

语法编译也通过：

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  backend\voice_trace.py backend\console_server.py `
  backend\target_workbench_adapter.py `
  tools\voice_real_machine_preflight.py `
  tools\voice_ledger_mcp_probe.py
```

### 3.2 历史埋点只能做卫生检查，不能当真机结果

当前旧样本混有历史测试/mock，不能作为本轮真机验收。最新汇总出现 missing，是因为当前还没有成批、隔离来源的真实耳机 turn；这不是“延迟为 0”，也不是 Target 已通过。

正式验收必须使用独立批次目录/文件名，并同时记录：

- 来源：`real_headset` / `wav_replay` / `mock`；
- pipeline：`legacy` / `target`；
- cold/warm；
- device index、采样率、模型/provider 版本；
- 成功轮、失败轮、取消超时、幽灵音频。

---

## 4. 真机操作顺序：现在不要直接做全双工

### 第 0 步：人工确认耳机

1. 插入耳机或确认蓝牙耳机连接；
2. Windows 声音设置中选择 `Headphones (Realtek HD Audio 2nd output)`；
3. 播放系统测试音，确认声音确实从耳机出来；
4. 保持输入使用麦克风阵列设备 1，输出固定为耳机设备 11；
5. 把设备编号和采样率记入本次批次，不要只依赖系统默认设备。

### 第 1 步：先做固定文本 Target，不接麦克风

目的：先拆掉 ASR 变量，证明：

```text
固定 transcript → SessionKernel → TargetVoiceChain → TTS → Playback
```

建议顺序：

- 5 次冷启动；
- 10 次暖机短句；
- 10 次长句；
- 10 次 interrupt/取消；
- 检查没有旧 generation 音频；
- 检查取消超时为 0。

这一阶段失败，先修 Target chain/TTS/playback，不进入实时 ASR。

### 第 2 步：再接 Target Streaming ASR

规则：

- partial 只更新 UI，不提交业务 turn；
- final 只能提交一次；
- 过期 generation 的 partial/final 全丢弃；
- 音频 ingress 只通过同一个 TargetVoiceRuntime；
- 耳机模式优先；不做外放 AEC。

### 第 3 步：耳机单工/半双工基线

建议批次：

- 短句 10 轮；
- 长句 10 轮；
- 连续对话 20 轮；
- 播放中插话 10 次。

每个批次单独保存 JSONL 和报告。不要用全局 `load_recent(100)` 混在一起算最终指标。

### 第 4 步：只在耳机证据通过后做“耳机全双工”

插话必须证明：

```text
barge_in_detected
  → TargetVoiceChain.interrupt()
  → TTS cancel
  → Playback stop evidence
  → 丢弃旧 generation
  → 新 turn 只提交一次
```

没有 `playback_stop` 的真实证据，只能说“发出了取消请求”，不能说“全双工插话成功”。

### 第 5 步：最后才评估外放 AEC / AudioDirect

必须先具备：

- render reference；
- 输入输出同步；
- 真正 AEC，而不是 RMS 门限；
- 回声残留指标；
- 能证明系统播放声不会被当成用户语音。

在这些条件之前，保持耳机路线，不训练、不切默认旧链、不做外放 A/B。

---

## 5. 延迟怎么测，避免误判

当前指标的语义要这样看：

- `speech_start → speech_end`：用户说话时长，不是系统延迟；
- `speech_end → asr_final`：端点/ASR 收尾延迟；
- `asr_final → llm_first_delta`：LLM 排队和首 token 延迟；
- `sentence_ready → tts_first_synth`：TTS 首段生成等待；
- `tts_first_synth → playback_start`：播放准备/设备启动；
- `barge_in → playback_stop`：插话到实际停止证据。

现有旧链代码仍有几个正式验收前必须补的埋点问题：

1. `tts_first_synth` 目前更接近“整句 TTS 返回后”，还不是首 PCM chunk；
2. `playback_start` 是软件提交播放，不是声卡/声学首音；
3. fallback ASR 之前打了 `asr_final`，会漏掉 fallback 耗时；
4. `turn_done` 可能早于播放真正完成；
5. RMS 门限 barge-in 不是 AEC。

因此本轮只把 trace 和边界准备到可测状态，没有把旧链的旧埋点包装成“真实物理低延迟”。

---

## 6. 下一步开发清单（按优先级）

### P0：先完成适配器 HTTP 接线，但保持默认 legacy

接线位置应在现有 `/voice` 请求解析处：

1. 读取 body；
2. `TargetWorkbenchAdapter.normalize_request(body)`；
3. 无 `pipeline` 时保持 legacy；
4. 只有 `pipeline=target` 且 `audio_route=headset` 时调用 Target composition；
5. 适配器实例必须注入已存在的 Target chain/runtime，不能在请求函数中 new kernel；
6. 统一把 chain 的结果转成响应；
7. 旧链异常时不得吞掉 Target 的 stop/cleanup evidence；
8. 请求级取消只调用 `chain.interrupt()`，不直接 cancel 新旧 task。

### P1：固定文本 Target 验收工具

新增一个不涉及麦克风的 bench：

- 为每轮生成 `batch_id`、`turn_id`、`trace_id`；
- 5 cold + 10 warm + 10 long + 10 interrupt；
- 输出 p50/p95/missing/timeout/ghost；
- 失败轮保存原始事件。

### P2：Streaming ASR 接线

将 `MediaAdapter → StreamingASRBridge → final-once gate → TargetVoiceChain` 接通；不要把 partial 当成提交。

### P3：耳机全双工插话

先完成 TTS cancel、playback stop evidence、generation 丢弃和单提交，再做连续 20 轮 + 10 插话。

### P4：外放 AEC

证据和指标齐全后再开始；当前不做。

---

## 7. 本轮停止条件

满足以下任一条件就停止继续扩大范围：

- 耳机实际输出未确认；
- Target 固定文本仍有取消超时；
- 出现旧 turn 幽灵音频；
- trace 缺少 stop evidence；
- HTTP 接线需要创建第二个 kernel/runtime；
- 需要重建 venv（当前没有这个必要）；
- 需要训练才能继续（当前链路诊断阶段不需要）。

---

## 8. 当前状态一览

| 项目 | 结论 |
|---|---|
| 台账索引/MCP 检索 | **已实际验证可用**，参考 `ledger:0510` |
| Python/依赖 | **可运行**，无需重建 venv |
| 软件预检 | **通过** |
| 物理耳机 | **待人工确认**，候选设备 11 |
| 适配器 | **边界与契约已完成，HTTP 尚未接线** |
| Target 隔离回归 | **84 tests 全部通过** |
| 真机 20 轮 | **未执行** |
| 耳机全双工 | **未放行** |
| 外放 AEC | **未开始** |
| 默认 `/voice` | **仍保持 legacy** |

**下一次实际操作不是训练，而是：确认耳机设备 11 → 固定文本 Target → 再 Streaming ASR → 再耳机插话。**

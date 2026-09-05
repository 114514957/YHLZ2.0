# TTSProviderPort v1 目标链路设计

状态：实验实现，未完成实机认证，未冻结。

范围：仅覆盖 YHLZ 目标语音链路的 TTS Provider 边界。旧 `backend/tts` 引擎、入口、WebUI、数据库、声音缓存和 `memory` 不在本轮改动范围内。

## 1. 收敛目标

Provider 可替换，但 Kernel 不感知 Qwen、CosyVoice、GPT-SoVITS 或 Edge 的私有接口。一个运行时周期只绑定一个 Provider；切换只能发生在严格空闲边界，旧 Provider 的停止证据未取得时不能启动新 Provider。

端口分成四个面：

| 面 | 统一内容 |
| --- | --- |
| 控制面 | `open`、`push_text(delta)`、`commit_text()` |
| 媒体面 | 单声道 24 kHz `s16le` PCM，播放前重排为 20 ms 帧 |
| 生命周期面 | `cancel(reason)`、`wait_stopped(timeout_s)`、`READY/DONE/STOPPED/ERROR` |
| 观测面 | 首个有效 PCM 块计时、连续性、队列、错误码、内存/显存和 RTF |

Provider 的能力声明只表示候选能力。只有当前设备、当前 Provider epoch 和真实运行证据同时满足验收，运行时才允许报告 C；否则为 B 或未认证。

## 2. 事件与媒体不变量

- 每个会话绑定 `session_id`、`turn_id`、`speech_id` 和 `provider_epoch`。
- Provider PCM 块带单调序号；缺口直接 fail-closed，重复块丢弃并计数。
- 适配器负责把可变大小块重排为 20 ms/480 samples 帧；Kernel 不接触 MP3、WAV 或 Provider 私有对象。
- 空块、全静音兜底和旧 epoch 事件不产生正常 `AUDIO_DONE`。
- 首块计时由 normalizer 在第一次有效 PCM 帧被接受时生成，Provider 不能自行伪造该事件。
- `DONE` 必须在 `commit_text()` 之后出现，并且至少有一个有效 PCM 帧；否则记录明确错误码。
- 事件日志只保留脱敏元数据，原始文本和音频不进入本端口的指标快照。

## 3. 双流时序

```text
open(request)
    ├─ audio_events(): READY ... PCM_CHUNK ... DONE
    └─ reasoner 输出 delta → push_text(delta) → ... → commit_text()
```

音频消费与文本增量并行。Provider 不支持文本双流时可以在适配器内部缓冲，但必须把 `text_stream=false` 如实声明，不能进入 C 路径。音频流结束而没有 `DONE`、或 `DONE` 早于 commit，均视为失败。

## 4. 取消、代际和切换

取消先调用 Provider 会话的 `cancel`，再在同一预算内等待 `wait_stopped`。会话打开前已经登记 turn 级控制句柄，避免“取消先到、Provider 后打开”的竞态。停止观察超时或异常会保留错误证据并阻止重启/切换，直到取得终态或人工处置。

Provider epoch 在 Provider 选择或运行时重开时递增。旧 epoch 的音频事件只计 stale，不得进入播放队列。活动回合不热切换；显式切换顺序为：

```text
停止当前回合 → 排空/隔离播放 → wait_stopped → 回收旧 worker
→ 打开新 Provider → 健康检查 → 递增 epoch 生效
```

## 5. Provider 与回退策略

首期优先验证本地 0.6B 流式 Provider；原生情绪能力另作为候选能力实测，不把 `VoiceStyle` 字段当作已认证情绪。Edge-TTS 只作为懒加载 B 回退或隔离对照：不预热、不并行请求、不抢占正常播放队列。主 Provider 句中失败时丢弃当前句，下一句才允许回退；主 Provider 恢复也只能在空闲时重新选择并验收。

Edge 外发文本是已接受的策略决定，必须在事件中记录 `network_fallback=true`、Provider、原因、speech_id、epoch 和网络错误码。Edge 的对照结果不能直接继承为 C 证据。

## 6. 当前实现与证据边界

已实现：`backend/tts_provider_port.py` 的类型、事件、PCM 帧化、连续性校验和指标；`TargetVoiceChain` 的可选 Provider 路径、文本双流、取消控制句柄、epoch 隔离和脱敏事件；`backend/tts_provider_worker.py` 的持久 worker 生命周期边界（可重用空闲/严格回收空闲、停止观察、代际隔离、健康与指标）；标准库合成契约测试。

`PersistentTTSProvider` 只接受显式注入的 worker factory 或 provider proxy。它不自行加载模型、不打开设备，也不把“声明为独立 worker”当作 C 证据。`reusable_idle` 仅表示同一存活 worker 可以接收下一会话；`strict_idle` 还要求所有已结束会话取得 `wait_stopped` 或 worker 退出证据，只有后者允许 `recycle`、`shutdown` 和 Provider 切换。进程/线程 transport 由后续真实 adapter 提供，旧代际事件在 facade 层先丢弃。

未实现/未认证：真实模型/进程 transport 适配、声卡播放端口、AEC、真实 TTFA/RTF、显存峰值、长跑和 C 认证。当前测试均为内存 Fake Provider，不代表本机硬件或模型可用性。

## 7. 后续门禁

1. 在隔离环境中登记真实 Provider，先静态契约检查，不启动设备。
2. 获得依赖/模型/设备测试授权后，完成短时 B 基线，记录 TTFA、连续性、取消和资源指标。
3. 通过真实 B/C 检查、停止收尾和回滚点后，才评估接入单一启动入口；WebUI 由其负责人处理。

本设计不改变 `memory`。运行期对 `memory` 仍仅允许重连、重启和重置。

# ADR-003: TargetPlaybackPort 播放边界

状态：设计通过，待实现与设备 B 基线；不构成 C 认证。

## 背景

Qwen Provider 已能输出 24 kHz 单声道 `s16le` PCM，并且组合根已完成无设备真实贯通。现有 `backend/audio_buffer.py` 是旧全局缓存：无容量上限、无 turn/generation、无播放停止证据，不能直接纳入目标链路。`TargetVoiceChain` 目前只能把 PCM 交给一个可选播放对象，尚未等待物理播放完成。

NEKO 的有效参考是持久输出流、有界抖动缓冲、初始预缓冲、完成哨兵、取消代际和迟到音频丢弃；不引入其多 Provider 队列、前端协议或全局会话实现。

## 决策

新增独立 `SoundDevicePlaybackPort`，只接受目标端口的 PCM：

```text
Qwen PCM 24 kHz s16le
  -> TargetPlaybackPort bounded queue / turn generation
  -> persistent sounddevice.OutputStream callback
  -> selected output device
```

播放端口不复用或修改旧 `audio_buffer`。输出设备 ID、采样率和通道数均为显式运行时配置；首轮选择本机已检查支持的 24 kHz 路径。若设备不支持该格式，端口 fail-closed，不在音频回调中临时重采样或静默切换设备。

## 端口契约

- `start()`：显式打开一个持久 `OutputStream`；无用户音频时保持静音。
- `play(AudioChunk, lease, signal)`：只入有界内存队列；24 kHz、单声道、`pcm_s16le` 是首期唯一输入。达到初始预缓冲后才实际输出，避免每个 Qwen chunk 单独调用播放 API。
- `finish(lease, signal)`：Provider `DONE` 后标记最后一块；仅在 callback 实际排空该 turn 的帧后返回成功。
- `interrupt(reason)` + `wait_stopped(timeout_s)`：递增播放 generation、清除旧帧，并等待 callback 至少一次确认静音；被打断的 turn 不得发正常 done。
- `close()`：在组合根关闭时停止和释放 stream；不写声音缓存、`memory` 或业务数据。
- `health()` / `metrics()`：仅提供队列深度、时长、停止/欠载计数、设备元数据和稳定错误码，不提供 PCM 或文本。

## 与 Kernel/Provider 的关系

当端口实现 `finish()` 时，`TargetVoiceChain` 只能在 `finish()` 返回后发布正常 `AUDIO_DONE`。取消时先清空播放队列并等待 `wait_stopped`，其队列状态同步到 `PersistentTTSProvider` 的严格空闲门禁，防止模型 Provider 在仍有旧音频时被切换或回收。

播放错误是目标语音路径核心故障：记录脱敏事件，运行时只能在严格空闲后重启；无 AEC 或未完成 ASR/输入/回声验证时仍为 B。

## 保护预算

- 预缓冲：300 ms（Qwen 24 kHz/20 ms 帧契约）。
- 队列容量：最多 32 帧、最多 5,000 ms；超过即 `VOICE-PLAYBACK-BACKPRESSURE`。
- 取消/停止观察：3 s 初始预算；设备侧实测不得突破当前运行时较小的有效预算。
- 设备 B 探针前仅用 fake `OutputStream` 做契约测试；真实设备测试不保存麦克风或播放 PCM。

## 不做的事

- 不将自播窗口、字符串回声过滤或旧 `audio_buffer` 当成 AEC 认证。
- 不把 OutputStream 可打开当作 C，或把回调静音当作 ASR/VAD/AEC 成功。
- 不修改 `start.bat`、WebUI、旧入口、业务数据、声音缓存或 `memory`。

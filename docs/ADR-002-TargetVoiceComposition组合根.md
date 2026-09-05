# ADR-002: TargetVoiceComposition 组合根

状态：执行中，未接入生产入口，未完成设备认证。

## 背景

目标链路已经具备 `SessionKernel`、`TargetVoiceChain`、`MediaAdapter`、`ASRBridge`、`TTSProviderPort` 和 Qwen 独立进程 Provider。旧 `backend/main.py` 仍直接持有多组全局 ASR、TTS、VAD、音频和会话状态。若在未建立唯一组装边界前把 Qwen Provider 接入旧入口，会形成第二套 turn、取消和生命周期所有权。

## 决策

新增 `TargetVoiceComposition`，仅作为目标链路的组合根：

```text
TargetVoiceComposition
  owns SessionKernel
  owns WakeWordGate("元亨")
  owns TargetVoiceChain
  owns one process-isolated Qwen TTSProviderPort
  creates one MediaAdapter + ASRBridge + TargetVoiceRuntime on explicit bind
```

组合根不导入 `backend.main`、`backend.tts_engine`、`conversation_manager`、数据库或真实 memory 实现。推理、播放、输入源、VAD、ASR、AEC 由调用方显式提供；缺失端口只能降级或阻止运行，不能静默替换为旧全局对象。

## 生命周期

1. 创建组合根不加载 Qwen 模型、不打开音频设备、不写事件文件或 memory。
2. `create_runtime()` 只允许一次，确保 Media、ASR 与 Chain 引用同一 Kernel/Chain。
3. `start()` 只转交给该唯一 runtime；Qwen 进程在首个 TTS 会话时惰性启动。
4. `shutdown()` 固定顺序：停止 runtime（或 chain）→ `wait_idle_stopped()` 取得 Provider 会话停止证据 → 在工作线程内调用同步 `shutdown()` 释放子进程。
5. 任一停止观察失败都抛出稳定组合根错误并禁止声称可回收、可切换或冻结。

## 约束

- `memory` 只能是 `ReadOnlyMemoryFacade`；其写操作仍 fail-closed。
- 唤醒词固定为“元亨”，仅在 idle 激活。
- Qwen 0.6B 的 `text_stream=false`、`native_emotion=false` 保持如实声明；组合根不得提升为 C 能力。
- Edge 不在组合根创建、预热或并行运行；下一句受控回退仍属于后续策略层。
- 设备枚举、捕获、播放、AEC、ASR 和完整 B/C 验收不因本 ADR 而通过。

## 验证

隔离测试须证明：对象唯一性、无旧入口导入、Provider 惰性创建、runtime 单次绑定、严格空闲后才关闭、memory 写入仍受阻。真实贯通探针须经此组合根运行 Qwen，而不是直接调用 Provider。

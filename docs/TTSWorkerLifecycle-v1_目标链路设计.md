# TTS Worker Lifecycle v1 目标链路设计

状态：实验实现，已完成标准库契约测试；未进行真实 Provider、设备或 C 认证。

## 1. 边界

`backend/tts_provider_worker.py` 位于 `TTSProviderPort` 与具体 Provider adapter 之间。它只负责 worker 的生命周期、会话身份和切换门禁，不负责模型加载、音频采集/播放、网络策略、业务数据或 `memory`。

worker 由调用方注入的 `worker_factory` 创建。factory 可以最终返回独立进程代理，也可以在测试中返回线程代理或 Fake；只有调用方能证明隔离时，才把 `worker_isolated=true` 写入能力声明。

## 2. 两级空闲

| 状态 | 允许的动作 | 必须满足 |
| --- | --- | --- |
| `reusable_idle` | 复用同一 worker 开始下一会话 | 无活动 turn/会话、无待处理文本、播放队列为空、worker 存活 |
| `strict_idle` | 切换 Provider、回收或关闭 worker | 上述条件，加上已结束会话全部取得 `wait_stopped`；worker 退出可作为等价停止证据 |

“没有新文本”不等于空闲。正在播放的尾帧、仍在执行的 `push_text/commit_text`、以及未确认的旧 session 都会阻止严格回收。

`open()` 在创建或绑定会话期间持有 `pending_open` reservation；停止、回收和关闭期间持有独占的 `pending_lifecycle` reservation。两类 reservation 都进入快照和阻断原因，防止并发调用在检查与实际操作之间穿过空闲边界。初始 `STOPPED -> READY` 启动只允许当前的 `open` reservation 跨过；普通调用不能借此绕过门禁。

## 3. 生命周期顺序

```text
open(request)
  -> 复用或惰性启动当前 worker
  -> 绑定 worker_generation + provider_epoch
  -> push_text / commit_text / audio_events
  -> DONE（会话槽可复用）
  -> wait_idle_stopped（取得切换证据）
  -> stop / wait_stopped
  -> recycle 后重新启动并健康检查
```

停止观察超时、异常或 worker 崩溃均记录稳定错误码。旧 generation 或旧 `speech_id/epoch` 的事件只计数，不进入播放。

## 4. 与 TargetVoiceChain 的关系

`TargetVoiceChain` 仍是 turn 的唯一 owner。它通过现有 `TTSProviderPort` 端口调用 facade；当 facade 提供 `assert_strict_idle()` 时，链路在替换 Provider 前执行该门禁。正常会话可以继续复用持久 worker；显式切换前必须调用 facade 的 `wait_idle_stopped()`，然后才允许 `recycle()` 或替换端口。

## 5. 验收与限制

标准库测试覆盖：factory 惰性启动与复用、双流会话、严格空闲阻断、`open`/生命周期并发 reservation、同步 `open` 不阻塞事件循环、停止证据、重建 generation、崩溃后会话注册表清理、旧 session 隔离、失败态不可复用和指标脱敏。测试不启动真实模型、麦克风、扬声器、AEC、Edge 网络或入口，因此不能把结果升级为 B 实机基线或 C 认证。

# Session Kernel Protocol v1（初稿）

> 状态：Proposed，尚未冻结  
> 适用项目：YHLZ2.0  
> 设计依据：YHLZ2.0 当前入口盘点 + NEKO 对话核心研究笔记  
> 目标：为文本、半双工语音、全双工语音和 Agent 任务提供同一套会话语义。

## 1. 设计原则

1. 一个 `session` 在任意时刻只有一个活动 `turn`；
2. Session Kernel 是 turn 所有权、取消和提交的唯一真值；
3. Provider、Agent、TTS、播放和 Avatar 不直接改变 Kernel 状态；
4. 事件至少一次投递，消费者必须幂等；
5. 先冻结可观察契约，允许内部实现和 Provider 替换；
6. 实时能力不足时显式降级，不伪装成全双工。

## 2. 术语

- **Session**：一次连续交互上下文，拥有唯一 `session_id`。
- **Turn**：从一次输入提交到该输入对应输出收尾的逻辑回合。
- **Kernel**：维护状态、所有权、序号、取消和恢复的核心组件。
- **Adapter**：把 HTTP、WebSocket、ASR、LLM、TTS、Agent 或 Avatar 接入协议的边界组件。
- **Commit**：允许把回合结果写入 history/memory 的明确时点。
- **Stale event**：属于已取消或已被新 turn 取代的事件，必须被丢弃或标记。

## 3. 事件封装

每个事件都使用以下封装。字段名和类型在 v1 内不随意变更：

```json
{
  "protocol_version": "1.0",
  "session_id": "sess_01J...",
  "turn_id": "turn_01J...",
  "seq": 42,
  "kind": "AUDIO_CHUNK",
  "actor": "assistant",
  "timestamp": "2026-08-28T15:30:00.123Z",
  "trace_id": "trace_01J...",
  "payload": {}
}
```

### 3.1 字段约束

| 字段 | 约束 |
|---|---|
| `protocol_version` | 语义版本，当前为 `1.0`；不兼容变更升主版本 |
| `session_id` | 不透明字符串；进程重启恢复时可延续，不复用给别的用户 |
| `turn_id` | session 内唯一；一个输入意图只能生成一个活动 turn |
| `seq` | session 内单调递增；由 Kernel 分配，Adapter 不得自造 |
| `kind` | 白名单事件类型；未知类型记录并按兼容策略处理 |
| `actor` | `user`、`assistant`、`system`、`tool`、`client` 之一 |
| `timestamp` | UTC ISO-8601；用于诊断，不用于替代序号排序 |
| `trace_id` | 跨 Provider/任务的关联 ID |
| `payload` | 事件专属对象；不得把公共字段塞入 payload |

## 4. 事件类型

| kind | 生产者 | 必要 payload | 说明 |
|---|---|---|---|
| `INPUT` | 输入适配器 | `input_type`, `text` 或 `audio_ref`, `final` | 用户文本、音频或转写片段 |
| `STATE` | Kernel | `from`, `to`, `reason` | 状态转移通知 |
| `TOKEN` | Reasoning Adapter | `text`, `index` | 可见或可过滤的增量文本 |
| `TOOL_CALL` | Agent Adapter | `call_id`, `name`, `arguments` | 工具请求，不代表已执行 |
| `TOOL_RESULT` | Tool Adapter | `call_id`, `ok`, `result` 或 `error` | 工具执行结果 |
| `TTS_TEXT` | Coordinator/TTS | `text`, `segment_id`, `final` | 发送给语音合成的文本片段 |
| `AUDIO_CHUNK` | TTS/Media Adapter | `audio_ref`, `sample_rate`, `format`, `bytes` | 音频片段；可外置存储引用 |
| `AUDIO_START` | Playback Adapter | `speech_id` | 实际开始播放，而非仅生成 |
| `AUDIO_DONE` | Playback Adapter | `speech_id`, `normal` | 仅正常收尾发送；中断流不得伪造 |
| `INTERRUPT` | 用户/VAD/系统 | `reason`, `supersedes_turn_id` | 抢占或显式取消当前 turn |
| `ERROR` | 任意组件 | `code`, `retryable`, `component`, `detail` | 错误和降级建议 |
| `COMPLETE` | Coordinator/Kernel | `outcome`, `committed` | turn 的最终收尾 |
| `ACK` | 消费者/客户端 | `ack_seq`, `consumer` | 需要确认的交付或回放位置 |

### 4.1 音频载荷

`AUDIO_CHUNK` 的 `payload` 必须明确：

```text
format: pcm_s16le | opus | wav
sample_rate: integer
channels: integer
duration_ms: integer
bytes 或 audio_ref: binary/reference
```

Provider 原生采样率、上行和下行格式不能隐含在配置名中。重采样只允许发生在明确的 Media Adapter 内。

## 5. 状态机

### 5.1 状态集合

```text
IDLE
LISTENING
THINKING
SPEAKING
DONE
INTERRUPTED
RECOVERING
```

### 5.2 转移表

| 当前 | 触发 | 目标 | 必须动作 |
|---|---|---|---|
| `IDLE` | 收到 `INPUT` 开始 | `LISTENING` | 创建或锁定 turn，发布 `STATE` |
| `LISTENING` | 输入提交/静音收尾 | `THINKING` | 固化输入，启动 Reasoning |
| `THINKING` | 首个可接受输出/TTS 片段 | `SPEAKING` | 建立输出代际，通知播放 |
| `SPEAKING` | 正常播放结束 | `DONE` | 发送 `AUDIO_DONE` 和 `COMPLETE` |
| `LISTENING`/`THINKING`/`SPEAKING` | 用户抢占或系统取消 | `INTERRUPTED` | 递增取消代际，停止/清理旧链路 |
| `INTERRUPTED` | 旧任务已失效 | `RECOVERING` | 丢弃 stale event，保留诊断信息 |
| `RECOVERING` | 可继续接收输入 | `LISTENING` 或 `IDLE` | 清理临时资源，允许新 turn |
| 任意非终态 | 不可恢复错误 | `RECOVERING` | 发布 `ERROR`，执行降级或等待人工恢复 |

`DONE` 和 `INTERRUPTED` 都是逻辑收尾；不能用“播放队列自然耗尽”推断正常完成。

## 6. 取消与抢占

Kernel 为每个 turn 维护单调的 `cancel_epoch`（实现可使用取消令牌，但语义必须等价）：

1. 创建 turn 时记录当前代际；
2. `INTERRUPT` 或新 turn 抢占时递增代际；
3. LLM、工具、TTS、播放在每个可中断边界检查代际；
4. 代际不匹配的事件标记为 stale，不得进入客户端、history 或 memory；
5. 取消操作必须幂等，重复取消不得生成第二次提交。

中断默认策略：停止播放、取消可取消任务、清空或隔离旧音频队列、发送 `INTERRUPT` 和 `COMPLETE(outcome=interrupted, committed=false)`；不发送正常的 `AUDIO_DONE`。

## 7. 提交和记忆规则

- 用户输入在 `INPUT(final=true)` 时成为可持久化候选；
- Assistant 内容只有在正常 `COMPLETE(committed=true)` 时进入正式 history/memory；
- 中断内容默认不写入正式记忆，可作为带 `partial=true` 的诊断记录；
- 工具结果必须以 `call_id` 幂等，不能因重连重复执行；
- Memory Facade 是唯一写入口，旧 API 只能读兼容或返回明确弃用错误；
- 事件先记录、视图后更新；重放或 reconcile 失败不能静默丢数据。

## 8. 投递、顺序与背压

- Kernel 负责分配 session 级 `seq`；消费者按 `(session_id, seq)` 去重；
- 允许至少一次投递，不承诺跨进程 exactly-once；
- `STATE`、`INTERRUPT`、`ERROR`、`COMPLETE` 不得因队列满被静默丢弃；
- TOKEN 和 AUDIO 可在事件已 stale 时丢弃，不能丢弃仍属当前 turn 的收尾事件；
- 所有队列有上限，达到上限时发布背压/降级事件；
- 慢消费者不能阻塞 Kernel 状态迁移。

## 9. Provider 能力协商

Provider 在建立 turn 前声明能力：

```json
{
  "concurrent_input": true,
  "streaming_output": true,
  "barge_in": true,
  "cancel_generation": true,
  "cancel_tts": true,
  "local_vad": true,
  "tool_call_streaming": false,
  "reconnect_resume": false
}
```

能力不足时的最低降级：

- 无 `concurrent_input`：进入 offline/半双工，并向客户端说明模式；
- 无 `cancel_generation`：停止消费旧输出，等待 Provider 自然结束；
- 无 `cancel_tts`：立即丢弃旧音频并禁止播放，但记录资源延迟；
- 无 `reconnect_resume`：重连后创建新 turn，不假装续播。

## 10. 适配器边界

概念接口如下，名称可在实现时调整，但职责不能混合：

| Port | 最低操作 | 不能做的事 |
|---|---|---|
| `InputPort` | 接收文本/音频、提交输入、报告 VAD | 写 history、直接控制播放 |
| `ReasoningPort` | 流式生成、工具调用、取消 | 改 Kernel 状态、写数据库 |
| `SpeechPort` | 文本片段合成、取消、正常收尾 | 决定 turn 提交 |
| `PlaybackPort` | 排队、开始、停止、报告 done | 重新生成文本 |
| `MemoryPort` | 幂等读写、提交、回放 | 被旧入口绕过 |
| `AvatarPort` | 消费 AvatarEvent | 反向抢占会话（除非发布用户事件） |

## 11. 隐私与安全

- 默认只向普通日志和非授权消费者发送脱敏文本；
- 原始音频、转写和屏幕数据使用显式权限和 TTL；
- `trace_id` 可用于定位，但不得包含 API Key、完整音频或敏感文本；
- 文件、插件、行动工具必须携带授权上下文和审计 ID；
- 未认证的跨网络入口不得启用协议写操作。

## 12. 兼容和版本策略

- v1 允许新增可选字段和事件；消费者必须忽略未知可选字段；
- 删除字段、改变状态语义、改变提交/中断含义时升主版本；
- 客户端握手声明支持的协议和能力；协商失败要显式报错；
- Adapter 可以支持多个协议版本，但 Kernel 只维护一个内部语义版本；
- 所有公共变更必须附 ADR、Schema 更新和契约测试。

## 13. 验收场景

1. 文本 turn 正常完成：事件序号连续，history 只提交一次；
2. LLM 生成中打断：旧 token 不再可见，新 turn 可开始；
3. TTS 播放中打断：播放停止，不发送正常 `AUDIO_DONE`；
4. 重复 `INTERRUPT`、重复 `ACK` 和重复工具结果：状态和数据不重复改变；
5. WebSocket 断线：按 Provider 能力恢复或新建 turn，不能重复播报；
6. Provider 超时：发布可定位 `ERROR`，按能力降级；
7. 两个 session 并发：事件、音频、记忆和取消互不串扰；
8. 回放事件日志：得到与在线状态一致的最终状态。

## 14. 待 ADR 决定的问题

- ADR-002：VAD/输入提交的唯一所有者和音频时钟；
- ADR-003：旧 `memory*` 与 Agent Memory 的迁移、读写和删除策略；
- ADR-004：`/ws`、`/ws/stream` 和 `/ws/avatar` 的版本与废弃路线；
- ADR-005：文件工具、插件和行动系统的授权/沙盒边界；
- ADR-006：本地 Provider 无取消能力时的资源回收和用户提示。

在上述 ADR 通过前，本协议保持 Proposed，不打 `architecture-freeze-v1` 标签。

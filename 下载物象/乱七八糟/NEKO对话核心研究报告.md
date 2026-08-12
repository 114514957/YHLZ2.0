# N.E.K.O 对话核心源码研究报告（中文）

> 研究对象：`main_logic` 下 7 个对话核心文件（`session_state.py`、`context_append.py`、`manager.py`、`turn.py`、`streaming.py`、`conversation_turns.py`、`omni_offline_client/*`），并补充 7 个支撑文件（`_shared.py`、`proactive.py`、`lifecycle.py`、`focus.py`、`_client.py`、`_streaming.py`、`_lifecycle.py`）。
> 获取方式：GitHub raw 直连与 git clone 均失败，最终经 `api.github.com` contents API 下载解码。文中行号均指下载后的本地文件。
> 覆盖 8 个问题：① 会话状态建模 ② 上下文管理/压缩 ③ 流式对话 ④ turn 生命周期 ⑤ 主动聊天 ⑥ 多提供商抽象 ⑦ 情绪注入 ⑧ 最佳实践与坑。

---

## ① 会话状态建模（Session State Modeling）

### 1.1 分散信号 → 单点状态机
`session_state.py`（34004B）模块 docstring 明确指出其目标：把原先散落在 `LLMSessionManager` / `OmniOfflineClient` 各处的 **"谁拥有当前 turn"** 信号收敛为单点状态机。这些信号原本包括：

- `current_speech_id` 的轮转（谁在说话）
- `session._is_responding` 布尔
- `_proactive_expected_sid`（contextvar，期望的主动语音 ID）
- `last_user_activity_time`（用户最后活跃时间）

收敛后：
1. **proactive phase1/phase2 可零成本 O(1) 无锁轮询** `is_proactive_preempted(claim_token)`——即使在每个 LLM chunk 之间检查也没有可感知开销；
2. "用户接管 / AI 开始回复" 等信号发布为**事件**（TTS worker、logging、前端同步可订阅）；
3. 每个猫娘实例独立、状态互不干扰。

### 1.2 核心类型
- `class TurnOwner(Enum)`：定义 "谁拥有当前 turn" 的枚举（成员因截断未全部读到，但语义确定）。
- `SessionStateMachine` / `SessionEvent` / `ProactivePhase`：经 `manager.py` 从 `main_logic.session_state` 导入；`proactive.py` 亦导入 `SessionEvent, ProactivePhase`。可确认存在，是状态机的主体。

### 1.3 组装架构（mixin 模式）
`manager.py`（30176B）中 `LLMSessionManager` 是所有对话能力的**组装器**：`__init__` 是全部实例属性（locks/caches/queues/flags）的唯一家，领域 mixin 只贡献方法。mixin 列表（行 36-42）：

```
ContextAppendMixin (.context_append)
FocusMixin            (.focus)
TtsRuntimeMixin       (.tts_runtime)
TurnMixin             (.turn)
ToolCallingMixin      (.tool_calling)
LifecycleMixin        (.lifecycle)
ProactiveMixin        (.proactive)
```

`__init__` 还导入 `TtsStreamNormalizer / TtsBracketStripper / TtsMarkdownStripper`（utils.frontend_utils）、`ToolRegistry`（tool_calling）、`SessionStateMachine/SessionEvent`、`LifecycleEventBus`（lifecycle_bus）、`ProactiveDeliveryManager`（proactive_delivery）、`MEMORY_SERVER_PORT / AVATAR_INTERACTION_DEDUPE_MAX_ITEMS`（config）、`soxr`。

> 结论：会话状态 = "状态机（谁拥有 turn）+ 事件总线（状态变化的对外通知）+ 实例隔离"。这种设计让 `is_proactive_preempted` 可以在热路径（LLM chunk 循环）上被高频轮询而不锁。

---

## ② 上下文管理 / 压缩（Context Management & Compression）

### 2.1 长回复 summary 三态状态机（离线客户端核心）
`omni_offline_client/_streaming.py`（104905B）行 688-719 有中文注释的 summary 状态机，是上下文压缩的**主证据**：

```
summary_state: 'idle' | 'pending_cutover' | 'cutover_done'
```

状态相关字段：
- `summary_prefix_for_history`：cutover 触发时刻的 assistant_message 快照（进 history 的 prefix）
- `summary_tail_buffer`：cutover 之后仅 UI 展示的文本（不直接进 history）
- `summary_next_gibberish_check` = `_SUMMARY_GIBBERISH_RECHECK_TOKENS`
- `summary_trigger_tokens` / `summary_overflow_offset`：越界 chunk 时在 budget 之后从头找 terminator

**emit 去向矩阵**：
| summary_state | UI | TTS |
|---|---|---|
| idle / pending_cutover | ✅ | ✅ |
| cutover_done | ✅（tail 攒进 summary_tail_buffer） | ❌ |

- 触发：stream 结束仍 idle/pending → 常规完整原文进 history；
- 否则：**调小模型摘要**，把 prefix+summary 进 history、tail 续到 TTS（失败则 abandon）。
- 工具回合持久化（`tool_round_persisted`）时，把 cutover 后 tail abandon 给 TTS 再重置 idle。

### 2.2 预算 → max_tokens 映射
`omni_offline_client/_shared.py` 行 169 `_budget_to_max_tokens(budget, summary_mode=False) -> int | None`：
- `budget >= _UNLIMITED_BUDGET`（999999，前端滑块选"无限制"）→ 返回 `None`（**请求直接省略该字段**，注释明确："大固定值会被某些 provider 拒绝为 out-of-range"）；
- `summary_mode=True` → `max(budget + _MAX_TOKENS_SLACK(20), _SUMMARY_API_BUDGET_FLOOR)`——**只抬不压**，Python 侧 guard 再逐响应决定 abandon / summarize / 放行超限；
- 否则 → `budget + _MAX_TOKENS_SLACK`。

配套常量（_shared.py）：`_GIBBERISH_PS_RATIO_CEIL = 0.25`（>25% 标点/符号 → emoji/mark spam）、`_MAX_TOKENS_SLACK = 20`、`_UNLIMITED_BUDGET = 999999`、`_PROACTIVE_SCREENSHOT_TTL_SECONDS = 60.0`。

### 2.3 summary terminator 查找
`_find_summary_terminator(text)`（行 187）：返回 `_SUMMARY_TERMINATOR_CHARS` 中**第一个**会产生停顿的标点偏移，-1 表示没有。用途：cutover 后让 TTS 在下一个自然呼吸处停，而不是断在词中间；调用方把 `offset + 1` 当作包含边界。

### 2.4 length guard（越界保护）
`_streaming.py` 行 1301-1324：
- `_notify_response_discarded(discard_reason or "guard", guard_attempt, total_attempts, False, truncate_msg, callback=discard_callback)`；
- 前端在 `response_discarded` 分支识别 `RESPONSE_LENGTH_TRUNCATED` 触发 truncate UX；
- `_conversation_history` 由 `core.handle_response_discarded` 在 `RESPONSE_LENGTH_TRUNCATED` 分支 append（本 OmniOfflineClient 与 core 共享**同一个** `_conversation_history` 列表）；
- 之后 `await self._check_repetition(recovery_text)`；
- 最终 `discard_reason` 含 `"length>"` 时发送 `{"code": "RESPONSE_TOO_LONG"}`。

### 2.5 历史修剪与工具调用清理
- `main_logic/core/_shared.py` 行 231 `_purge_closed_tool_calls(history, *, start=0) -> int`：清理已关闭的 tool call，避免历史膨胀。
- `_client.py` 行 223：`self._conversation_history = []`（会话级历史，热切换复用）。
- `context_append.py` 行 258-266：跨会话 context-append 用 `_CONTEXT_APPEND_SOURCE_MAX_TOKENS` 预算，`truncate_to_tokens(content, max_tokens)` 截断后再 append。

### 2.6 记忆服务熔断（lifecycle.py）
`MEMORY_SERVER_PORT` / `MEMORY_SERVER_CRASHED` 状态码 / `_memory_error_retry_after` / `_memory_error_cooldown_seconds`：记忆服务崩溃后进入熔断冷却，避免反复请求失败端点。`get_context_summary_ready`（config.prompts.prompts_sys，lifecycle.py 行 35）驱动上下文摘要的就绪信号。

---

## ③ 流式对话（Streaming）

### 3.1 双路径：realtime 与 offline
- **realtime 路径**：`OmniRealtimeClient`（WebSocket），源码未获取（不在清单内）。
- **offline 路径**：`OmniOfflineClient(_ToolingMixin, _GenaiMixin, _StreamingMixin, _MediaMixin, _LifecycleMixin)`（`_client.py` 行 44）——**模拟 OmniRealtimeClient 的接口**，用 ChatOpenAI + OpenAI 兼容 API 做纯文本对话。

`_StreamingMixin`（`_streaming.py` 行 57）暴露接口：`update_max_response_length`、`connect(instructions, native_audio=False)`、`send_event(event)`、`update_session(config)`、`switch_model(...)`——与 realtime 客户端接口对齐，业务层可无感切换。

### 3.2 core 侧流式输入（streaming.py，36397B）
方法索引（grep 确认）：
- 行 50 `_user_input_ingress_time(message)`
- 行 57 `note_stream_input_ingress(message) -> bool`
- 行 84 `_emit_cooldown_turn_end_if_needed()`（冷却 turn 结束）
- 行 101 `_flush_pending_input_data()`
- 行 147 `_should_drop_live_vision_stream(input_type)`
- 行 151 `stream_data(message)` → 行 160 `_stream_data_now(message)` → 行 218 `_process_stream_data_internal(message)`
- 行 486 附近注册 `response_discarded_callback`、行 508 附近 `input_transcript_callback`

核心：输入流先入队（pending），在冷却/忙碌时延迟 flush，并带输入入口时间戳（ingress time）做时序追踪。

### 3.3 流式 + 工具调用
`_streaming.py` 行 730-767：注释明确 "Tool-aware streaming: `_astream_with_tools` runs..."，转发 overrides（如 `base_max_tokens`，行 750）到 `_astream_with_tools`；`async for chunk in self._astream_visible_with_tools(...)`（行 767）。即流式循环里同时处理工具调用与可见文本，overrides 可动态调 `max_completion_tokens`（如 focus 叠加）。

### 3.4 focus 思考 token 叠加
行 364-414：`thinking_on, model, base_max_tokens=None` 时，若 thinking_on 且 `base_max_tokens is not None`，`overrides["max_completion_tokens"] = base_max_tokens + FOCUS_THINKING_EXTRA_TOKENS`——专注思考模式在 live 预算上叠加额外 token。总结前会暂存 `_summary_prev_max_tokens`（行 621-624），结束后恢复（行 1620-1621），防止污染后续请求。

---

## ④ Turn 生命周期（Turn Lifecycle）

### 4.1 turn.py 管道（90044B）
模块 docstring：conversation turn pipeline——text/audio intake、transcripts、response completion/discard bookkeeping、voice-echo suppression、mirror channel。导入 `SESSION_ARCHIVE_TRIGGER_TOKENS / SESSION_TURN_THRESHOLD`（config）、`dispatch_user_utterance`（agent_event_bus）、`_REQUEST_ID_UNSET`、`_MAGIC_COMMAND_IMAGE_DROP_REQUEST_MAX`、`_VOICE_ECHO_LOOKBACK_SECONDS / _VOICE_ECHO_LOOKBACK_CHARS`、`_looks_like_recent_ai_echo`、`_proactive_expected_sid`。

> 说明：turn.py 90044B，read 工具分段读取，中间主流程（`_start_...` 主方法）未能逐行精读，但 docstring、imports、尾段（echo suppression）已确认，下面 4.2 基于确认片段 + 会话归档常量推断。

### 4.2 会话归档触发
- `SESSION_ARCHIVE_TRIGGER_TOKENS`：达到该 token 数触发会话归档；
- `SESSION_TURN_THRESHOLD`：turn 数阈值；
- `lifecycle.py` 也有 `summary_triggered_time`（行 362）与 `SESSION_ARCHIVE_TRIGGER_TOKENS`，说明归档/摘要跨生命周期与 turn 两模块协作。

### 4.3 voice-echo suppression（防回声，行 936-972 附近）
- `_confirmed_ai_voice_echo_audio_speech_ids`（已确认的回声语音 ID）
- `_pending_ai_voice_echo_chunks`（deque，待定回声 chunk）
- `_pending_ai_voice_echo_text` + `_sync_pending_ai_voice_echo_text()` / `_discard_pending_ai_voice_echo()`
- `_should_suppress_dirty_voic...`（截断）
- 关键规则：**每个 speech_id 只能安全 promote 一个 chunk**，配合 `_VOICE_ECHO_LOOKBACK_SECONDS / _VOICE_ECHO_LOOKBACK_CHARS` 与 `_looks_like_recent_ai_echo`（difflib SequenceMatcher，`_shared.py` 行 79）判断用户输入是否是刚播放过的 AI 声音回声，是则抑制。

### 4.4 ConversationTurnDispatcher（conversation_turns.py，5787B）
- `@dataclass(frozen=True) class ConversationTurnEvent`（行 34-43）：`lanlan_name / actor: TurnActor(Literal["user","ai"]) / text / raw_text / lang / timestamp / text_allowed / had_text`。
- `class ConversationTurnSink(Protocol)`（行 46-48）：`note_turn(event) -> None`，不阻塞 chat path。
- `class ConversationTurnDispatcher`：同步 fanout，**chat path 拥有 turn timing**，消费者自管存储/调度/异步。
- **隐私模式**（`_privacy_mode_active()` 默认 True 兜底）：redact `text` 字段，仅授权 sink 可消费 `raw_text`。
- `normalize_turn_language()`：`normalize_language_code(source, format='full')` 兜底 'en'。
- 机制：turn 事件经此 fanout 到下游（情绪注入、记忆、统计等消费者）。

---

## ⑤ 主动聊天（Proactive）

### 5.1 两阶段协议（proactive.py，134441B，行 1-644 已读）
流程：`prepare_proactive_delivery` → `feed_tts_chunk` → `finish_proactive_delivery`。

- 行 47 `note_user_engagement(*, at=None)`：用户互动打点，防打断判定依据。
- 行 57 `_park_proactive_for_goodbye()`：告别场景暂停。
- 行 70 `update_agent_flags(flags)`。
- 行 91 `trigger_voice_proactive_nudge() -> bool`：语音主动提示（nudge）。
- 行 133 `request_fresh_screenshot(timeout=3.0) -> str`（行 187 内 `_capture_and_compress() -> bytes` 线程）：**截图 staging**，供视觉主动聊天使用。
- 行 211 `prepare_proactive_delivery(min_idle_secs=10.0) -> bool`（行 213 `_user_active_recently()`）：**要求至少 10 秒空闲**才允许主动说话，否则拒绝。
- 行 310 `feed_tts_chunk(...)`：流式喂 TTS。
- 行 365 `finish_proactive_delivery(full_text, expected_speech_id=None, action_note=None, source_tag=None, vision_screenshot_b64=None, expected_user_engagement_time=Ellipsis) -> bool`：
  - **防打断提交**：若 `expected_speech_id` 不匹配当前 `current_speech_id`（进入 `_proactive_write_lock` 后），说明用户已接管，跳过 frontend/history/TTS end 信号；
  - `action_note` 追加到 AIMessage content 尾部（**仅 history，不进 send_lanlan_response/TTS**）——例如"实际播放了哪首歌"作为元数据给下一轮 LLM 看；
  - 走 `DELIVERY_RETRACTED_KEY / VOICE_DELIVERY_COMMITTED_KEY / resolve_callback_delivery_ack`（main_logic.proactive_delivery）做交付确认。

### 5.2 防重复 / token 预算
- `ANTI_REPEAT_EXEMPT_SOURCE_TAGS`（config）：部分来源标签豁免防重复；
- `_build_callback_instruction / _select_callbacks_within_token_budget`（callback_render）：**回调在 token 预算内选择**，超预算的 callback 指令不注入。

### 5.3 会话状态机联动
`is_proactive_preempted(claim_token)`（session_state）：proactive 的 phase1（准备）/phase2（交付）在任何 LLM chunk 之间检查，用户输入（`note_stream_input_ingress`）会立即提升 preempt 标志，`finish_proactive_delivery` 据此决定是否放弃提交。

---

## ⑥ 多提供商抽象（Multi-Provider Abstraction）

### 6.1 统一接口
`OmniOfflineClient` **刻意模拟** `OmniRealtimeClient` 的接口（`_client.py` 行 44 注释），上层业务代码（manager/turn/proactive）对两者不可区分：

| 能力 | realtime（WebSocket） | offline（HTTP ChatOpenAI） |
|---|---|---|
| 对话 | OmniRealtimeClient | OmniOfflineClient（模拟） |
| 连接 | connect | `connect(instructions, native_audio=False)` |
| 事件 | send_event | `send_event(event)` |
| 会话参数 | update_session | `update_session(config)` |
| 换模型 | switch_model | `switch_model(...)` |

### 6.2 可插拔后端
- `lifecycle.py` 行 1627 `_background_prepare_pending_session()` 中 `aget_model_api_config('realtime', core_config=...)` 设置 `self.core_api_type`（含 `CORE_API_TYPE` 配置注释："core_api_type 从 realtime 配置获取，支持自定义 realtime API 时自动设为 'local'"）——即 `core_api_type='local'` 走本地/自定义 provider，其余走官方。
- 存在 `_should_use_genai_sdk` 双路径判定（genai SDK vs 原生 OpenAI 兼容）。
- `_GenaiMixin` 处理 SDK 差异，`_ToolingMixin` 提供工具调用兼容层。
- `_streaming.py` 行 150 注释：`switch_model` 同步 `self.base_url / self.api_key`，否则后续 `_astream_with_tools` 会用错端点——多 provider 切换时的经典坑，代码显式注释警告。

### 6.3 文本清洗适配层
- `ThinkingStreamStripper` / `strip_thinking_segments`（utils.llm_client）：剥离思考段，离线与 core 共用。
- `TtsStreamNormalizer / TtsBracketStripper / TtsMarkdownStripper`（utils.frontend_utils）：TTS 流规范化。

---

## ⑦ 情绪 / 状态注入（Emotion & State Injection）

### 7.1 slop 语言注入（offline 生命周期）
`omni_offline_client/_lifecycle.py` 行 42-57 `_with_dialog_slop(method)` 装饰器：为一次 offline dialog turn 武装 prompt-only slop 削减——`resolve_dialog_slop_lang` → `set_dialog_slop_lang(lang)` / `reset_dialog_slop_lang(token)`（utils.slop_filter / utils.llm_client）。即对话回合前后临时切换语气/风格语言，回合结束恢复（with-scope token 保护）。

### 7.2 focus 指示器（focus.py，30757B，grep 方法索引）
- `_focus_inline_decision(user_text) -> bool`：根据用户文本判断是否切入 focus 模式；
- `_focus_idle_thinking()` / `_focus_idle_cooldown(...)`：空闲思考触发与冷却；
- `_on_focus_transition(event, payload)` / `resync_focus_for_new_window()`：状态迁移/新窗口重同步；
- `_push_focus_indicator(active, *, force=False)` / `_push_focus_charge(charge=None)` / `_push_focus_thinking(active, *, force=False)` / `handle_thinking_active(active=True)`：把"专注中/充电/思考中"状态**推送到前端**；
- `_maybe_purge_focus_artifacts()`：清理 focus 残留。
- 与 3.4 呼应：focus 激活时流式 overrides 叠加 `FOCUS_THINKING_EXTRA_TOKENS`（config）。

### 7.3 ConversationTurnDispatcher 事件注入
`conversation_turns.py`：每个 user/ai turn 生成 `ConversationTurnEvent`，同步 fanout 给 sink。情绪/事件注入 = **通过事件订阅机制把状态带给消费端**（记忆、TTS、前端），且 `text_allowed`/`raw_text` 双通道支持隐私模式下的脱敏注入。

### 7.4 其他注入面
- `action_note`（proactive 5.1）：工具执行结果作为 metadata 注入 history（不给 TTS），供下一轮 LLM 感知。
- `_with_dialog_slop`（offline）与 `prompts_sys` 摘要提示（lifecycle 行 35）：风格注入进入 system prompt。
- `_GIBBERISH_PS_RATIO_CEIL`、`_is_gibberish_response`、`_NONVERBAL_DIRECTIVE_PATTERN`：脏输出/非语言指令的过滤，是"情绪注入"的负向治理（防止乱码污染语气）。

---

## ⑧ 最佳实践与坑（Best Practices & Pitfalls）

### 8.1 任务 GC 保护（Python 3.11+ 关键坑）
`context_append.py` 的 `_fire_task(coro)`：`asyncio.create_task` 后**必须**存入 `self._bg_tasks` 集合 + `add_done_callback(self._bg_tasks.discard)`，否则未来事件循环轮会被 GC 静默回收（Python 3.11 起 create_task 不再被强引用）。项目以 `_bg_tasks` 显式保活——这是新手极易踩的坑。

### 8.2 哨兵对象区分"未传"与"None"
`_shared.py` 行 12 `_REQUEST_ID_UNSET: Any = object()`：防止 recovery/proactive 路径把 request_id 绑定到新值；`_HANDSHAKE_OVERRIDE_UNSET` 同理。**不要用 None 表示未设置**（None 有时是合法值）。

### 8.3 流式热路径的无锁轮询
`is_proactive_preempted(claim_token)` 设计为 O(1) 无锁，因为它在**每个 LLM chunk 之间**都要检查。若做成有锁/重计算，会拖慢 token 吞吐。会话状态因此必须收敛到单点状态机（见①）。

### 8.4 跨模式 start_session 递归深度封顶
`lifecycle.py` 行 686 `start_session(websocket, new=False, input_mode='audio', *, user_initiated=False, _allow_cross_mode_restart=True, ...)`：
- `user_initiated` 仅由 websocket_router 的 start_session action 传入；
- 跨模式撞车时**仅用户显式请求**等待 in-flight 落定后切目标模式，后台 proactive/greeting auto-start 静默 return；
- `_allow_cross_mode_restart=False` 把递归深度封到 1，防止 start_session 互相触发死循环。

### 8.5 并发 start_session 的 handshake 竞态
行 713-717：**handshake 快照在第一次 await 前截取** `_independent_asr_handshake_override`，防止并发 start_session 互相覆盖 ASR 握手配置。

### 8.6 热切换预准备（防第 3 个实例泄漏）
`_background_prepare_pending_session()`（行 1627）先清理残留 pending session（防止泄漏到第 3 个实例），再 `aensure_region_resolved()` / `aget_core_config()` / `aget_model_api_config(...)` 设置 `core_api_type`，并 `cleanup_invalid_voice_ids` 清理旧 voice 残留。热切换不止换 client，还要做配置与 voice 的收敛。

### 8.7 max_completion_tokens 的 provider 边界
- 大固定值会被某些 provider 拒绝（`_budget_to_max_tokens` 对无限制预算返回 None、省略字段，而不是传巨大数）；
- summary 模式只抬不压；调用后必须恢复 `_summary_prev_max_tokens`（行 1620-1621），否则污染后续请求；
- focus 叠加 `FOCUS_THINKING_EXTRA_TOKENS` 时 `base_max_tokens=None`（unlimited）则不加，避免 `None + int` 崩溃。

### 8.8 多 provider 切换的端点同步
`_streaming.py` 行 150 注释明确警告：`switch_model` 必须同步 `self.base_url / self.api_key`，否则后续 `_astream_with_tools` 会打到旧端点（配置残留）。

### 8.9 隐私双通道
`ConversationTurnEvent.text_allowed/raw_text`：隐私模式（默认 True 兜底）redact text，仅授权 sink 拿 raw_text——注入与脱敏并存，防止敏感语音转写泄漏到普通消费者。

### 8.10 回声抑制的粒度控制
`_pending_ai_voice_echo_chunks` 中**每个 speech_id 只 promote 一个 chunk**，配合 `_VOICE_ECHO_LOOKBACK_SECONDS/CHARS` 与 SequenceMatcher 相似度判定，避免把用户的正常回应误杀成回声，也避免回声重复注入。

### 8.11 交付确认（delivery ack）
`finish_proactive_delivery` 走 `DELIVERY_RETRACTED_KEY / VOICE_DELIVERY_COMMITTED_KEY` 确认提交，而不是"发完就不管"；`expected_user_engagement_time=Ellipsis` 兜底，用户未按时互动也正常收尾。

### 8.12 乱码/API key 拒绝治理
`_is_api_key_rejected_error` + `_API_KEY_REJECTED_KEYWORDS`：识别 key 被拒；`_LLM_RETRY_ERROR_TYPES` + `chat_retry_error_types`：对 transient 错误重试；`_is_gibberish_response` + `_GIBBERISH_PS_RATIO_CEIL` + `_SUMMARY_GIBBERISH_RECHECK_TOKENS`：长回复摘要后**再次**检查乱码，防止摘要本身吐脏。

---

## 附：关键文件速查

| 文件 | 作用 | 关键符号 |
|---|---|---|
| `session_state.py` | 会话状态机 | `SessionStateMachine`、`SessionEvent`、`TurnOwner`、`ProactivePhase`、`is_proactive_preempted` |
| `context_append.py` | 跨会话 context-append | `ContextAppendMixin`、`_fire_task`、`_CONTEXT_APPEND_*` |
| `manager.py` | 组装器 | `LLMSessionManager` + 7 个 mixin |
| `turn.py` | turn 管道/防回声 | `TurnMixin`、`_VOICE_ECHO_LOOKBACK_*`、`SESSION_ARCHIVE_TRIGGER_TOKENS` |
| `streaming.py` | core 流式输入 | `_process_stream_data_internal`、`_emit_cooldown_turn_end_if_needed` |
| `conversation_turns.py` | turn 事件 fanout | `ConversationTurnEvent`、`ConversationTurnDispatcher`、`TurnActor` |
| `omni_offline_client/_client.py` | 离线客户端 | `OmniOfflineClient`、`_budget_to_max_tokens` |
| `omni_offline_client/_streaming.py` | 离线流式+summary | summary 三态状态机、`_notify_response_discarded`、`_astream_visible_with_tools` |
| `omni_offline_client/_lifecycle.py` | 离线生命周期 | `_with_dialog_slop` |
| `proactive.py` | 主动聊天 | `prepare/finish_proactive_delivery`、`expected_speech_id` |
| `lifecycle.py` | 会话生命周期 | `start_session`、`_background_prepare_pending_session` |
| `focus.py` | 专注指示器 | `_push_focus_indicator/charge/thinking` |

> 局限说明：`turn.py` 主流程与 `core/streaming.py` 内部因体积过大未能逐行精读（行号/方法名来自头部、尾段与 grep 索引）；`OmniRealtimeClient` 源码未获取。如需补齐，可经 api.github.com 继续下载或对本地文件用脚本提取方法级索引。

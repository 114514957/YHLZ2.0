# YHLZ 2.0 语音段超时丢弃问题 → 修正方案(待 Qwen 评估)

> 针对实际运行日志:
> `[WARNING] 上一轮还在处理 (等 2s 仍超时), 跳过本次语音段`
> 用户现象: 上一次话没说完这一次话又接上了, 导致用户得重新说。
> 涉及文件: `对话DEMO\voice_chat_demo.py`(1118 行, 真实代码)
> 日期: 2026-08-03

---

## 一、问题现象(真实日志)

```
19:51:36,862 VAD 检测到语音开始 (第一段)
19:51:37,960 VAD 检测到语音结束
19:51:37,964 第一段采集完成 2.20s / 35200 samples
19:51:37,973 ASR 识别开始(首次, 初始化降噪/AGC ~0.5s)
19:51:38,463 VAD 检测到语音开始 ← 用户又说第二句 (第一段 ASR 还没完)
19:51:39,512 第一段识别: "ιι" (乱码, 含 NaN/Inf 回退警告)
19:51:39,520 LLM 开始生成回复
19:51:39,793 第二段采集完成 2.40s / 38400 samples
...之后无任何输出 (第二段被丢弃) ...
```

第二次实测(20:06): 明确打出 `[WARNING] 上一轮还在处理 (等 2s 仍超时), 跳过本次语音段`。

**用户感知**: 一句话(或补充的话)在 AI 还没处理完上一句时被吞掉 → 用户被迫重说。

---

## 二、根因(真实代码)

`_processing` 锁的持有时间 = **整轮对话**(ASR + LLM 流式生成 + TTS 合成 + 等待播放开始), 期间用户新语音段只能等 2s, 超时即丢。

### 2.1 `_on_speech_end` 的 2s 硬超时(voice_chat_demo.py:751-767)

```python
def _on_speech_end(self, audio: np.ndarray):
    for _ in range(20):
        if not self._is_processing_pending:
            break
        time.sleep(0.05)
    if not self._processing.acquire(timeout=2.0):      # ← 2s 超时直接丢弃
        logger.warning("上一轮还在处理 (等 2s 仍超时), 跳过本次语音段")
        return
    try:
        self._handle_turn(audio)
    finally:
        self._processing.release()
```

### 2.2 锁被持有多久?——`_handle_turn` → `_generate_and_speak` 全程

```python
def _handle_turn(self, audio):          # :769
    text = self.asr.transcribe(audio)   # ASR
    asyncio.run(self._generate_and_speak(text))   # ← 阻塞直到生成+合成+播放启动完成
```

`_generate_and_speak`(:785)在语音模式下阻塞的时长 ≈
- LLM 流式生成全部(首字 1.5~2.4s, 整段更长)
- 各句 TTS 合成 task `gather`(最多等 5s)
- `await play_queue.put(None)` + dispatcher 收尾
- 最后 **等待 play_start 标记最多 10s**(:1017-1020)
- 然后才 `history.append` + `tracker.report()` + 返回 → 锁释放

→ 一轮可能 **5~15s+**, 而新语音段只等 **2s**。

### 2.3 矛盾点: 播放期间其实已"排队不丢", 但播放前/播放后窗口会丢

| 阶段 | 用户说话走哪条路 | 结果 |
|---|---|---|
| AI 播放中 (`_paused=True`) | `_callback` 的 `_paused` 分支 → `_pending_segments` 排队 | ✅ 方案A已实现, 播完追加 |
| AI 生成中/尚未播放 (`_paused=False` 但锁被持有) | `_on_speech_end` → 等锁 2s | ❌ 超时丢弃 |
| 播放刚结束 (`set_paused(False)` 后, `_generate_and_speak` 还没返回) | `_on_speech_end` → 等锁 2s | ❌ 超时丢弃 |

**核心 bug**: 锁的生命周期覆盖了播放, 而播放本身又靠 `_paused` 冻结录音; 播放一结束用户立刻说话, 锁却还没释放 → 被吞。

---

## 三、候选修正方案(请 Qwen 评估权衡)

### 方案 A: 锁持有范围收窄——播放完成即释放锁, 不覆盖播放等待

- 锁只保护 **ASR + LLM 流式生成 + TTS 合成入队** 这一段核心逻辑;
- "等待 play_start" 与播放期间的逻辑不与 `_processing` 锁绑定;
- 播放由 Player 线程驱动, `on_play_done` 时本轮对话已可认为"处理完毕", 锁应已释放;
- 播放期间用户说话 → 走 `_paused` 插话排队(已有); 播放结束锁已释放 → 新语音立即处理。

**好处**: 不改变"播放期间不打断、排队追加"的既定交互; 消灭"播放刚结束即说话被吞"窗口。
**风险**: LLM 生成中的 2s 超时窗口仍在(此时用户说话仍需等锁)。

### 方案 B: `_on_speech_end` 超时不丢弃, 改为入队等待(复用 pending 机制)

- 把 `_on_speech_end` 的 `acquire(timeout=2.0)` 失败分支从"丢弃"改为"把语音段 push 进 `_pending_segments`";
- 上一轮释放锁后, 由 `_process_pending_segments` 统一消化;
- 与播放期插话共用一个队列(注意区分"播放期插话"与"非播放期插话"的来源/顺序)。

**好处**: 任何情况下用户的话都不丢。
**风险**: 若 LLM 生成很慢(数秒), 排队的语音段会积压, 用户连说多句时上下文延迟叠加; 需控制队列上限与"过期/合并"策略。

### 方案 C: 组合(A + B)

- 锁范围收窄到 ASR+LLM+合成入队(解决播放后窗口);
- 残余的"LLM 生成中"窗口用队列兜底: 超时则入队, 不丢弃;
- 队列带 TTL/合并: 相邻短段合并成一句, 过久清空。

### 方案 D: 彻底回归 barge-in(中断式)

- 用户任何时刻说话 → 中断当前 LLM/TTS/播放, 立即处理新语音(原方案 A 之前的 barge-in 逻辑);
- 与"播放期间不打断排队"的既定设计冲突, 仅作备选。

---

## 四、请 Qwen 重点回答的问题

1. A/B/C/D 哪个最贴合本场景?(约束: 保持"播放期间不打断、播完追加"的交互, 但**任何用户语音段都不能被静默丢弃**)
2. 若选 B/C: `_pending_segments` 是否需要区分"播放期插话"和"非播放期补话"? 历史顺序如何保证(播放期插话应紧跟刚播的 assistant 回复, 非播放期补话应算新 user 轮)?
3. 若选 A: "锁范围收窄"具体怎么改最稳——锁从 `_handle_turn` 的哪一行释放? `on_play_done` 回调线程与 `_processing` 锁如何协作不产生并发 race?
4. 排队语音段的 TTL/合并策略: 何时该合并成一句? 何时该丢弃? 上限多少?
5. 是否需要给"语音段被排队/被处理"补日志, 便于真机观察?

---

## 五、涉及的真实代码位置速查

- `_on_speech_end`: voice_chat_demo.py:751
- `_handle_turn`: voice_chat_demo.py:769
- `_generate_and_speak`: voice_chat_demo.py:785(锁持有全程)
- 等待 play_start: voice_chat_demo.py:1017-1020
- Player 播放完成回调 `on_play_done`: voice_chat_demo.py:600-605 / :704
- 播放期插话排队 `_pending_segments`: voice_chat_demo.py:229 / :329-342
- `_process_pending_segments`: voice_chat_demo.py:709-737
- `set_paused`: voice_chat_demo.py:235-247

---

## 六、落地记录 (2026-08-03 20:18, 已实施方案 C)

Qwen 推荐方案 C(锁范围收窄 A + 超时入队 B), 已按真实代码落地并单测通过:

### 6.1 改动点(voice_chat_demo.py)

1. **Recorder.push_pending()**: 新增, 把超时语音段统一入队 _pending_segments(与播放期插话同一队列), 保证不静默丢弃。
2. **_on_speech_end(原 :751)**: 锁 cquire(timeout=2.0) 超时不再 eturn 丢弃, 改为 ecorder.push_pending() 入队 + 若无敌消费者则启动 _process_pending_segments 线程, 并打 [QUEUE] 日志。
3. **_process_pending_segments(原 :709)**: 
   - 加 _pending_lock 消费者互斥(同一时刻只一个线程消化队列), 防止播放期插话与超时补话双线程并发;
   - 按 ts 时间戳顺序消化; **相邻 <1.5s 且合并后 ≤50 字的短段合并成一句**(碎片如"对/然后/那个"变一句);
   - 每段 ASR → _is_echo 防循环 → syncio.run(_generate_and_speak(text)); _generate_and_speak 内部自行 append user 消息, **不再重复 append**;
   - 锁被占用时 **while 重试而非丢弃**。
4. **锁范围收窄(A 的轻量版)**: _generate_and_speak 尾部等待 play_start 从 10s 降到 3s(:1064), 缩短 _processing 锁持有, 缩小"播放结束后立刻说话"的被吞窗口。
5. **VoiceChatDemo.__init__**: 新增 self._pending_lock。

### 6.2 与 Qwen 伪代码的差异(按真实代码修正)

- Qwen 建议 self._gen_token = time.monotonic(): 实际 _gen_token 是 int 计数器, 已维持原语义, 未改;
- Qwen 建议 _handle_turn(None): 不可行, 已改为直接 _generate_and_speak(text)(ASR 已在队列消化阶段完成);
- Qwen 建议 TTL: 因锁范围收窄后队列消化极快, 未加硬 TTL(保留"合并+上限"); 后续如需再加;
- 上下文窗口: 维持 messages = system + history[-8:], 每段 user 消息由 _generate_and_speak 内统一 append, 不重复、不超窗。

### 6.3 单测结果(全部 PASS)

| 用例 | 结果 |
|---|---|
| 语法 st.parse | OK |
| 3 段相邻(<1.5s)短段合并成一句 | PASS |
| 相邻短段合并 + 间隔>1.5s 拆分成两句 | PASS |
| 消费者互斥(第二个 _process_pending_segments 直接返回) | PASS |
| _on_speech_end 锁超时 → 入队而非丢弃 | PASS |
| 历史顺序: user 消息紧跟上一 assistant 回复 | PASS |

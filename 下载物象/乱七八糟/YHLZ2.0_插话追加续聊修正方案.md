# YHLZ 2.0 用户插话不打断、追加续聊 修正方案

> 基于真实代码 `对话DEMO\voice_chat_demo.py`(1032 行)修订
> Qwen 原方案的 3 处硬伤: 前提错误 / 回声策略不成立 / 上下文窗口遗漏
> 日期: 2026-08-03

---

## 〇、方案一句话

AI 播放期间用户说话 **不打断播放**, 正常走 VAD 采集 + 入队; AI 这句播完后, 排队语音段 ASR → 作为**新 user 消息**追加到刚播的 assistant 回复之后 → LLM 接着回应该插话。

## 一、真实代码现状(必须认清的前提)

`Recorder._callback`(每帧 100ms)在 `_paused=True`(AI 播放)时:

```python
# voice_chat_demo.py:236-252 (真实代码)
with self._lock:
    if self._paused:
        # 回声过滤: 播放期间不正常识别, 但检测 barge-in 打断
        if is_speech and self.player and self.player.is_playing and not self._barge_in_triggered:
            self._barge_in_count += 1
            if self._barge_in_count >= self._barge_in_threshold:
                self._barge_in_triggered = True
                threading.Thread(target=self._do_barge_in, daemon=True).start()
        else:
            if not is_speech:
                self._barge_in_count = 0
        self._preroll.append(frame)   # 只进 1s 环形缓冲
        return                          # ← 关键: 直接返回, VAD 状态机被冻结!
```

**关键事实**: 播放期间 `detect_speech()` 虽然被调用, 但 `_paused` 分支直接 `return`, **`_flush_speech` 永远不会在播放期间触发**。Qwen 假设"播放期间 VAD 判定说完→入队"是不成立的, 必须先解冻。

同时 `_speech_started` 在 `set_paused(True)` 时被强制置 False(:192)。

## 二、设计总览

```
AI 播放中 ── 用户说话 ──────────────────────────────
   │ 麦克风帧(含 AI 回声)
   ▼
Recorder._callback (_paused=True)
   │ 1. 解冻 VAD 状态机(播放期间也走 speaking→silence)
   │ 2. 音量遮蔽: 帧 RMS 需 > AI 播放音量 × 1.6 才算"语音"(滤回声)
   │ 3. 完整采集 → VAD 判定说完 → _flush_speech_paused()
   ▼
_pending_segments deque (带时间戳, maxlen=8 防爆)
   │  AI 这句播放完成
   ▼
Player._loop 播放结束分支 → 回调 demo.notify_play_done()
   ▼
主线程空闲 → _process_pending_segments()
   │ ASR → 相似度防循环 → history.append(user 插话)
   ▼
复用 _handle_turn 的 LLM→TTS→播放
```

## 三、代码修改点(最小 diff)

### 3.1 Recorder: 解冻 VAD + 音量遮蔽 + 排队

**`__init__` 新增:**

```python
self._pending_segments = collections.deque(maxlen=8)  # (audio, ts, dur) 插话排队
self._queue_lock = threading.Lock()                    # 排队段锁
self._ai_play_volume = 0.0                             # 当前 AI 播放音量(回声基准)
```

**`_callback` 的 `_paused` 分支改造**(替换 :236-252):

```python
with self._lock:
    if self._paused:
        # 播放期间: 解冻 VAD 状态机, 但用音量遮蔽滤回声
        frame_rms = float(np.sqrt(np.mean(frame ** 2)))
        speech_now = is_speech and (frame_rms > self._ai_play_volume * 1.6)
        self.vad.detect_speech(frame, SAMPLE_RATE)   # 推进状态机(供 is_speaking 判断)

        if not self._speech_started and speech_now:
            self._speech_started = True
            self._start_time = time.time()
            self._frames = list(self._preroll)        # 预滚动兜底(仅取末尾 1s)
            self._preroll.clear()
        elif self._speech_started:
            self._frames.append(frame)

        # VAD 判说完 → 排队(不打断播放)
        if self._speech_started and not self.vad.is_speaking():
            self._flush_speech_paused()
            self._speech_started = False

        self._preroll.append(frame)
        return
```

**`set_paused(True)` 时不再重置 `_speech_started`**(否则插话被清零): 改为只清 barge-in 计数。

**新增 `_flush_speech_paused` 与对外接口:**

```python
def _flush_speech_paused(self):
    frames = self._frames
    self._frames = []
    if not frames:
        return
    audio = np.concatenate(frames)
    duration = len(audio) / SAMPLE_RATE
    if duration < MIN_SPEECH_DURATION:
        return
    with self._queue_lock:
        self._pending_segments.append((audio, time.time(), duration))
    logger.info(f"🗒️  播放期间采集到插话 {duration:.2f}s, 已排队")

def has_pending(self) -> bool:
    with self._queue_lock:
        return len(self._pending_segments) > 0

def pop_pending(self):
    with self._queue_lock:
        return self._pending_segments.popleft() if self._pending_segments else None

def set_ai_play_volume(self, rms: float):
    """Player 播放时回调: 记录当前 AI 播放音量作为回声基准"""
    self._ai_play_volume = rms
```

**`_do_barge_in` 删除**(方案 A 不打断, 原 barge-in 逻辑整体移除)。`set_paused(False)` 保持重置插话临时状态。

### 3.2 Player: 播完回调 + 音量上报

**`_loop` 播放循环中, 边播边上报音量**(`_audio_callback` 内或每 chunk):

```python
# _audio_callback 里, 在 outdata 填充后:
if self.recorder:
    self.recorder.set_ai_play_volume(float(np.sqrt(np.mean(outdata[:, 0] ** 2))))
```

**新增播放完成回调字段与触发**(`__init__`):

```python
self.on_play_done: Optional[callable] = None
```

**在播放结束分支(:571-573)触发:**

```python
else:
    self.is_playing = False
    logger.info("✅ 播放完成")
    if self.on_play_done:
        try:
            self.on_play_done()      # 通知 demo 处理排队插话
        except Exception as e:
            logger.error(f"on_play_done 回调失败: {e}")
```

注意: 播放被打断分支(:554-570)也需上报, 但被打断时排队段不处理(等下一轮), 可只在 `else` 正常完成分支触发。

### 3.3 VoiceChatDemo: 排队段处理 + 防循环 + 历史顺序

**`run_voice_mode` 绑定回调:**

```python
self.player.on_play_done = self._on_play_done
```

**新增 `_on_play_done`(线程中处理, 不抢 `_processing` 之前先排队):**

```python
def _on_play_done(self):
    if not self.recorder.has_pending():
        return
    threading.Thread(target=self._process_pending_segments, daemon=True).start()

def _process_pending_segments(self):
    while True:
        item = self.recorder.pop_pending()
        if item is None:
            break
        audio, ts, dur = item
        # 等待上一轮 _handle_turn 完全结束(释放 _processing 锁)
        if not self._processing.acquire(timeout=5.0):
            logger.warning("等待上一轮结束超时, 丢弃排队段")
            continue
        try:
            # 新 token, 防旧任务串台
            my_token = self._gen_token
            text = self.asr.transcribe(audio, sample_rate=SAMPLE_RATE) or ""
            text = text.strip()
            if not text:
                continue
            # 防循环: 与刚播文本相似度高于阈值则丢弃
            if self._is_echo(text):
                logger.info(f"⛔ 插话识别 '{text[:20]}' 疑似回声, 丢弃")
                continue
            # 追加为新的 user 消息(在 assistant 回复之后)
            self.history.append({"role": "user", "content": text})
            logger.info(f"🗣️  插话(排队段): {text}")
            asyncio.run(self._generate_and_speak(text))
        finally:
            self._processing.release()
```

**`_is_echo`(防循环, 简单字符重叠):**

```python
def _is_echo(self, text: str) -> bool:
    last_assistant = next((m["content"] for m in reversed(self.history)
                           if m["role"] == "assistant"), "")
    if not last_assistant:
        return False
    overlap = len(set(text) & set(last_assistant))
    ratio = overlap / max(len(set(text)), 1)
    return ratio > 0.6   # 与刚播内容 >60% 字符重叠视为回声
```

## 四、上下文窗口处理(用户重点关注)

现状 `:673` `messages = system + history[-8:]`。插话会让窗口滚动变快, 旧上下文被挤出。

**规则**:
1. **插话三元组保底**: `_process_pending_segments` append user 后, 若 history 长度 > 16, 把最旧的 user+assistant 对**压成一行摘要**注入(`summary` 缓存), 而非直接丢。
2. 演示期简化: 保持 `history[-8:]`, 但插话必须紧跟其对应的 assistant 之后追加(禁止插到中间), 保证 LLM 读到"刚说的 + 插话"。
3. 若排队段积压 ≥ 3 条(用户连续插话), 只处理最新 1 条, 旧的丢弃并提示——避免 8 条窗口被 3 条插话冲垮。

## 五、风险与回退

| 风险 | 缓解 |
|---|---|
| 回声误识别 | 音量遮蔽(×1.6)+ ASR 后相似度防循环 双保险 |
| 排队段处理时锁冲突 | `_processing.acquire(timeout=5)` + 失败丢弃 |
| 插话窗口冲垮上下文 | 摘要压缩 + 积压只取最新 |
| 音量遮蔽误杀(用户声小) | 阈值降到 ×1.3 可调; AEC 声卡优先时关闭遮蔽 |
| 插话采集被 AI 声覆盖 | 靠音量差; 无法根治时退化为"播放结束立即开新一轮 VAD" |

## 六、验收

1. AI 说 3 句, 第 1 句播完用户插话 → AI 不打断播完 → 插话被识别并追加 → AI 回应该插话
2. 播放期间纯 AI 回声 → 不产生假插话(防循环生效)
3. 连续 2 轮插话 → 历史顺序: [user][assistant][user插话][assistant][user插话]... 不串台
4. 端到端仍 ≤5s(插话处理在播放完后台进行, 不影响主链路)

---

## 七、落地记录(Qwen 4 点微调后已实现并测试)

### 7.1 落地内容

| 项 | 实现位置 | 说明 |
|---|---|---|
| 音量遮蔽滑动平均 | `Recorder.set_ai_play_volume` + `Player._audio_callback` | 一阶低通 `0.8*old + 0.2*new`, 静音帧不骤降 |
| 插话短阈值 | `MIN_PENDING_SPEECH_DURATION=0.2` | 播放期间插话独立阈值, 不沿用 0.3 |
| 插话采集只收语音帧 | `_callback` `_paused` 分支 | 静音帧不 append, 保证 duration 是真实插话长度(否则尾静音虚高时长, 短阈值失效) |
| asyncio 隔离 | `_process_pending_segments` 内 `asyncio.run` | 子线程无全局 loop, 安全(与本项目 `_handle_turn` 一致) |
| 历史顺序保护 | `_is_processing_pending` 标志 + `_on_speech_end` 前 20×50ms 等待 | 保证插话紧跟其 assistant 回复之后 |
| 防循环 | `_is_echo`(字符重叠 >60%) | 测试: 高度重叠判回声 ✓, 新内容放行 ✓ |
| barge-in 移除 | `_do_barge_in` 整个删除 | 方案 A: 一律不打断 |

### 7.2 行为单测结果(全部通过)

| 用例 | 预期 | 实测 |
|---|---|---|
| t1 播放中插话(音量遮蔽通过) | 入队 | pending=1 ✓ |
| t2 插话音量 < AI×1.6(回声) | 不采集 | pending=0 ✓ |
| t3 纯回声帧 | 不误采 | pending=0 ✓ |
| t4 静音帧后平滑值 | 不骤降 | 0.0288 ✓ |
| t5 短插话 <0.2s | 丢弃 | pending=0 ✓ |

### 7.3 回归验证

- 语法检查通过
- 文本模式完整链路(引擎加载→LLM→TTS→播放→延迟报告)正常, 无报错, 播放完成回调不触发(无排队段时 no-op)
- 端到端 3900ms(LLM 首字 2417ms 为 API 波动, 不影响链路正确性)

### 7.4 待真机验证

语音模式下真实插话(需麦克风+播放): 插话采集→排队→播完触发→ASR→追加→回复 全流程尚未在真实声学环境跑通, 属下一步。

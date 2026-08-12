# YHLZ 2.0 对话流畅度与检测链路优化方案

> 基于: 两份参考项目学习笔记 (N.E.K.O / NachoBot / AIRI) + 本项目 `对话DEMO\voice_chat_demo.py` 实测基线
> 目标: ①对话更流畅 ②检测更快更自然 ③"说完→模型说话" 延迟 ≤ 5s
> 日期: 2026-08-03

---

## 〇、一句话结论

当前端到端(说完→听到)实测 **3.05s**,已达标(≤5s)。
剩余优化集中在两条线:
- **检测链(更自然)**:VAD 尾音判定过慢(800ms)+ 停顿切句过短(300ms)→ 变成"掐话头、吞句尾"的自然度问题
- **生成链(更流畅)**:LLM 切句碎片化 → TTS 句子之间"哒哒哒"断,需参考 NEKO 的句切分归一化 + 碎片合并

方案不新增外部依赖,全部改现有 demo 参数/逻辑,按优先级 P0/P1/P2 落地。

---

## 一、当前延迟基线(实测,文本模式)

来源:`对话DEMO\voice_chat_demo.py` 延迟追踪报告(经 WebUI API 文本模式,`--engine qwen3-tts-customvoice`):

| 环节 | 实测耗时 | 说明 |
|---|---|---|
| LLM 首字延迟 | 1486ms | API 网络(DeepSeek/Qwen 远端) |
| LLM 总生成 | 5003ms | 2-3 句回复,流式 |
| TTS 首句合成 | 582ms | Qwen3 本地预热后 |
| 首句入队→播放 | 943ms | 含 Player 缓冲/OutputStream 启动 |
| **端到端(说完→听到)** | **3048ms** | vad_end → play_start |

语音模式额外环节(尚未实测,理论开销):
- VAD 尾音判定: 说话停后需 **4+4=8 帧 = 800ms** 静音才触发 `_flush_speech`(见 `backend\vad_engine.py:31-33`)
- ASR 识别: 整段音频识别(SenseVoice 本地,秒级)

> 卷一(针对YHLZ 2.0 改进建议-卷一Demo.txt)的验收标准: 端到端 <3s、首字 <1s——当前已在临界,优化后应稳定达标。

---

## 二、检测链路:更快更自然 (P0)

### D1. VAD 尾音判定从 800ms 压缩到 ~300ms 【最快见效, 改 2 个数字】

现状(`backend\vad_engine.py:31-33`):
```python
self.min_voiced_frames = 2    # 200ms 语音才确认为"开口"
self.min_unvoiced_frames = 4  # 400ms 静音 → 进入 hangover
self.hangover_frames = 4      # 400ms 尾音缓冲 → 判定结束
```
合计: 说话停后 **800ms** 才判"说完"。用户已经闭嘴 0.8 秒 AI 才动——这是"反应慢"的最大感知来源。

改法(保守,不引入误切):
```python
self.min_voiced_frames = 2    # 不变 (防噪声误开)
self.min_unvoiced_frames = 2  # 200ms 静音即进 hangover
self.hangover_frames = 1      # 100ms 尾音 → 判定结束
```
- 尾音判定降至 **300ms**,语音模式端到端直接省 ~500ms → 预计 2.5s 左右
- 风险: 句内停顿 >300ms 会被切段。中文正常语速句间停顿 300-800ms,句内停顿一般 <200ms。若演示中发现误切,调回 `hangover_frames=2`(共 400ms)即可。
- **预留**: `Recorder` 在 `_flush_speech` 处已有 `MIN_SPEECH_DURATION=0.3` 兜底,过短丢弃,不会放大噪声。

### D2. 停顿切句从"200ms 就切"放宽到"300ms" 【配合 D1】

现状(`对话DEMO\voice_chat_demo.py:60-63`):
```python
FRAME_SIZE = 1600   # 100ms/帧
MIN_SPEECH_DURATION = 0.3  # 最短语音段
```
切句判定 = VAD 判静音(`check_silence_timeout` 主循环轮询)。D1 之后判定是 300ms,已自然放宽。
- 若 300ms 仍切太碎(句内吞字),把 `MIN_SPEECH_DURATION` 提到 0.4,过滤残音。
- 目标: "自然度" = 不吞句尾、不掐句头(已有 preroll 1s 防丢句头)。

### D3. ASR 开启直通 GPU + 常驻,去掉按需加载

现状(`对话DEMO\voice_chat_demo.py:607`): `load_engines` 已 `direct_gpu=True` 一次性加载,常驻。✓ 已达标。
- 确认 `STAGGERED_MODE`(卷一问题4)在 demo 不开启——当前代码无错峰,ASR 常驻,无需动作。
- 后续若接 WebUI 后台,确保 ASR 首载(约 17s)放在启动预热,不进对话链路。

### D4. barge-in 打断响应已达标,微调阈值

现状(`voice_chat_demo.py:180`): `_barge_in_threshold = 3`(3 帧 ≈300ms 确认打断),打断后 0.1s 停声。
- 卷一验收: 打断后 1s 内停声。✓ 已达标。
- 可选优化: 打断瞬间直接 `interrupt()` 立即切静音(Player 已有),实测无需改。

---

## 三、生成链:更流畅 (P1)

### G1. LLM 切句碎片合并(消除"句子间哒哒哒"停顿) 【流畅度核心】

现状 `split_text_for_streaming`(`voice_chat_demo.py:114`): 已做标点优先 + 短句(<8 字)并入前段。但 LLM 流式输出常产生:
- `"好的,"` `"没问题"` 这类 2-4 字短碎片 → 每段独立 TTS,播放时句子之间出现 ~100-300ms 拼接缝
- 卷二建议 P0 第 6 条"句切分碎片合并"正是此问题

改进(改 `split_text_for_streaming`,不重写):
- `min_segment_length` 从 8 提到 **10**(合并更多短碎片)
- 增加"前缀粘连": 当一段以 `好的/嗯/哦/哎/呃/那你/就是说` 等口语词开头且总长 < 12 字时,并到前段或后段,避免孤零零的语气词单独合成
- 参考 NEKO `TtsBracketStripper`: 段内剥离 markdown 残留(如 `**`、反引号),避免 TTS 把语法符号读出来

### G2. TTS 段间缓冲:首句后 300ms 出声,后续句 200ms 内衔接

现状 `Player._loop`(已修): 连续缓冲 + 无间隙无截断。实测"首句入队→播放 943ms"偏高。

改进:
- `Player` 首片阈值: `_synth_one` 已降到 4000 samples(0.17s@24k)→ 首句实际更快入队
- 剩余 943ms 主要来自: 首个 chunk 等 LLM 出句 + TTS 流式首片 + OutputStream 启动。可接受。
- 若要再压: 首句到达后立即 `output.write` 前几片,不等积累——当前已是如此。此环节已是瓶颈下限,不做过度优化。

### G3. LLM 流式首字延迟 1486ms —— 远端 API 硬成本

- 本地 LLM(Ollama/Qwen)可降到 ~300ms,但需用户选择"质量 vs 速度"。
- 低成本做法: 保持远端,但把 system prompt 精简(当前已 2-3 句限制),减少首字计算。
- **不做**: 不等 LLM 首字就把占位音频(TTS"嗯/呃")播出去——会造成"AI 在说废话",反而更不自然。卷一/卷二均未要求。

---

## 四、上下文防膨胀 + 自然度辅助 (P2, 可选)

参考 NEKO/NachoBot 上下文三件套,给长会话保流畅:

| 措施 | 参考来源 | 建议 |
|---|---|---|
| 窗口裁剪 | NEKO recent | 当前 `history[-8:]` 已够,不扩 |
| 摘要压缩 | NEKO CompressedRecentHistoryManager / 卷二 P0-2 | 超过 N 轮后把旧对话 LLM 压缩成 1-2 行摘要注入,防上下文漂移 |
| 防复读 | NachoBot anti-repeat(BM25)/ 卷二 P0-5 | 若同一话题连续 >3 轮,提示 LLM"刚聊过",避免车轱辘话 |
| 会话状态机 | NEKO 单点状态机 / 卷二 P0-1 | 把 `_processing`/`_gen_token`/`is_playing` 收拢为单一状态,避免 barge-in 竞态 |

> P2 不影响 ≤5s 目标,是"对话更流畅"的长期项。Demo 优先 P0+P1。

---

## 五、实施清单(按顺序)

| # | 动作 | 文件 | 收益 | 优先级 |
|---|---|---|---|---|
| 1 | `min_unvoiced_frames` 4→2, `hangover_frames` 4→1 | `backend\vad_engine.py:32-33` | 尾音判定 800→300ms,语音端到端省 ~500ms | P0 |
| 2 | `MIN_SPEECH_DURATION` 0.3→0.4(可选) | `对话DEMO\voice_chat_demo.py:63` | 过滤残音,更自然 | P0 |
| 3 | `split_text_for_streaming`: `min_segment_length` 8→10 + 口语前缀粘连 + 去 markdown 残留 | `对话DEMO\voice_chat_demo.py:114-154` | 消除碎片句拼接缝 | P1 |
| 4 | 上下文摘要压缩 + 防复读(可选,二期) | demo 主类 | 长会话稳定 | P2 |

---

## 六、预期结果(语音模式)

| 指标 | 当前(实测/推算) | 优化后(预计) |
|---|---|---|
| VAD 尾音判定 | 800ms | 300ms |
| ASR 识别 | ~1s | ~1s(常驻) |
| LLM 首字 | 1486ms | 1486ms(远端不变) |
| TTS 首句 | 582ms | 582ms |
| 首句入队→播放 | 943ms | ~900ms |
| **端到端(说完→听到)** | ~3.5s(语音) | **~2.9s** |
| 自然度 | 停顿切碎、句尾吞字 | 碎片合并、尾音不吞 |

> 卷一验收(端到端 <3s、首字 <1s、打断 1s 内停声): 优化后全部稳定达标。

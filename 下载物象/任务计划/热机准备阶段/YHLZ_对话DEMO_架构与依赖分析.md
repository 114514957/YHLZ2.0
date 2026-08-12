# YHLZ 对话DEMO 架构与依赖分析

> 对象：`D:\YHLZ2.0\对话DEMO\`（voice_chat_demo.py 1007 行）
> 日期：2026-08-09 | 判定：**可借鉴**（保留分析，运行入口已由 webui_server.py 取代）

---

## 一、文件清单（20 文件）

| 文件 | 行数 | 角色 |
|---|---|---|
| `voice_chat_demo.py` | 1007 | 核心语音对话主程序（CLI） |
| `demo_webui.py` | 262 | Flask 启动器（起后端+日志流+延迟报告） |
| `demo.html` | — | WebUI 页面 |
| `start_demo.bat` | 43 | 启动脚本（:5050） |
| `smoke_test.py` | 134 | 冒烟测试（HTTP 链路） |
| `test_comprehensive.py` | 277 | 综合测试（健康/聊天TTS链/WS/Live2D/端口/ASR重置） |
| `test_latency.py` | 217 | 延迟测试 |
| `test_live2d.py` | 41 | Live2D 测试 |
| `test_ws.py` | 24 | WebSocket 测试 |
| `test_m04_endpoints_smoke.py` | 95 | **Mock 重量级引擎后 import main** 路由注册测试 |
| `test_memory_policy.py` | 204 | 内存策略测试（引擎共存预算） |
| `test_prompt_cache_spike.py` | 205 | TTS prompt 缓存（首提/恢复/加速） |
| `test_qwen3_voice_cache.py` | 190 | Qwen3 声音缓存测试 |
| `test_tts_adapters.py` | 232 | TTS 适配器测试 |
| `test_tts_fallback.py` | 201 | TTS 回退测试 |
| `test_v1_final_audit.py` | 360 | V1 最终审计 |
| `test_voice_identity_compat.py` | 338 | 声音身份兼容 |
| `test_voice_style_unified.py` | 363 | 声音风格统一 |
| `test_reset.py` | 26 | 重置测试 |
| `.env` | 22 | 环境变量 |

---

## 二、核心程序架构（voice_chat_demo.py）

### 2.1 顶层结构

```
LatencyTracker (76)          延迟追踪: vad_start/vad_end/asr_start/asr_done/
                             llm_start/llm_first/tts_start/tts_done/play_start
split_text_for_streaming (118)  句级切分 (min_segment_length=4, 句号类触发)
Recorder (204)              录音: sounddevice + VAD(Silero) + 静音超时 +
                             barge-in 排队 (pending 队列)
Player (397)                播放: sounddevice + 打断回调 (on_play_done/
                             on_player_interrupt)
VoiceChatDemo (623)         主控: 引擎加载/轮次处理/流式生成/历史
main (1133)                 CLI: --engine TTS选择 / --text 纯文本 / --once
```

### 2.2 语音对话流程

```
麦克风 → Recorder (VAD 检测)
  → 静音超时 → _on_speech_end
    → _processing.acquire(timeout=2s)      [互斥, 超时转排队]
    → _handle_turn
        → asr.transcribe                   [ASR]
        → _generate_and_speak (async)
            → llm.generate_stream          [LLM 流式]
            → split_text_for_streaming     [句级切分]
            → 每句 asyncio task 并行 TTS   [并行预合成]
            → play_queue → dispatcher(seq) → Player 顺序播放
    → _processing.release
```

### 2.3 关键机制（可借鉴点）

| # | 机制 | 实现 | 价值 |
|---|---|---|---|
| 1 | **并行预合成 + 顺序播放** | 每句独立 `_synth_one` task → `play_queue` → `_play_dispatcher` 按 seq 顺序入队 | 解决句间卡顿，TTFB 低（首片 0.17s 立即入队） |
| 2 | **barge-in 中断令牌** | `my_token = self._gen_token`，`interrupted()` 对比；LLM/TTS 各步检查 | 用户插话立即打断，历史不污染（中断回滚 user 消息） |
| 3 | **防回声循环** | `_is_echo`：识别文本与上一条 assistant 文本字符重叠率 > ECHO_OVERLAP_RATIO → 丢弃 | 防止 ASR 把 TTS 播放识别回来形成死循环 |
| 4 | **互斥 + 超时排队** | `_processing.acquire(timeout=2)`，超时音频转 pending 队列 + 后台线程 `_process_pending_segments` | 并发轮次不丢话 |
| 5 | **延迟追踪器** | LatencyTracker 各阶段 mark + report | 逐环节耗时统计（对话层健康指标） |
| 6 | **合成失败哨兵** | `_synth_one` finally 必发 `(seq, None, None, True)` | 失败不卡死 dispatcher |
| 7 | **分段阈值优化** | 首片立即送，后续累积 0.17s flush；句级 min_segment_length=4 | 低首字延迟 |
| 8 | **引擎卸载** | 退出时 asr/tts/vad.unload() | 释放显存 |
| 9 | **回退路径** | 流式无 chunk → 整段 synthesize 回退 | 兼容非流式引擎 |
| 10 | **Mock import 测试** | test_m04_endpoints_smoke：MagicMock 替换重量级引擎后 import main | 不加载模型即可测路由 |

---

## 三、依赖关系

### 3.1 backend 依赖（5 个）

```
backend.config          (配置)
backend.asr_engine      (Whisper/FunASR 识别)
backend.tts_engine      (TTS 兼容层 → tts/manager)
backend.llm_engine      (LLM 流式生成)
backend.vad_engine      (Silero VAD)
```

### 3.2 第三方依赖

```
numpy / sounddevice (录音播放)
requests / websocket-client (测试)
flask (demo_webui)
```

### 3.3 测试依赖 backend

```
test_memory_policy.py      → backend.memory_policy
test_tts_adapters.py       → backend.tts.adapters
test_voice_style_unified   → backend.tts.voice_style
test_prompt_cache_spike    → backend.tts.qwen3_customvoice
test_tts_fallback.py       → backend.tts 引擎回退链
test_voice_identity_compat → backend.voice_identity + context_manager
test_m04_endpoints_smoke   → backend.main (Mock 引擎)
```

---

## 四、借鉴判定建议

### ✅ 强烈建议借鉴（并入热机/后续）

1. **并行预合成调度模式**（play_queue + seq dispatcher）
   → 可提炼为通用 `StreamingPlayDispatcher` 组件，供 V10.5 多模态/具身播放复用
2. **barge-in 中断令牌模式**（token 对比 + 各步检查 + 历史回滚）
   → 对话层与 Embodied 层融合时的标准打断语义
3. **防回声循环检测**（_is_echo 重叠率）
   → 热机运行必配（真实设备回环防护）
4. **LatencyTracker 阶段追踪**
   → 直接升级为热机 Health Metrics 的对话链路版本
5. **Mock import 测试策略**
   → 与 V6.3 教训一致，推广到所有重量级模块测试

### ⚠️ 视情况借鉴

6. 互斥+超时排队 → 已在 embodied RLock 体系内，可参考超时语义
7. 分段阈值/回退路径 → TTS 管理器已具备，参考其参数化方式

### ❌ 不建议迁移

- demo_webui.py / demo.html / start_demo.bat（已被 webui_server.py 取代）
- 测试脚本可归档进 backend/voice 相关 tests（按需挑选）

---

**YHLZ · 元 · 亨 · 利 · 贞**

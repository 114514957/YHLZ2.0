# 语音对话 DEMO 框架文档（YHLZ 2.0）

> 生成日期：2026-08-03
> 源码位置：`D:\YHLZ2.0\对话DEMO\`
> 本文档为该目录源码浏览后的框架梳理，非代码副本，仅作结构/调用关系参考。

---

## 1. 目录结构

```
D:\YHLZ2.0\对话DEMO\
├── voice_chat_demo.py        # 核心：语音对话闭环 Demo（1118 行）
├── demo_webui.py             # WebUI 启动端：Flask 控制面板 + 子进程管理（321 行）
├── start_demo.bat            # 一键启动脚本（port 5050）
└── templates\
    └── demo.html             # Web 控制台前端（522 行）
```

## 2. 整体架构

```
┌────────────┐   ┌─────┐   ┌─────┐   ┌──────────┐   ┌──────┐   ┌───────┐
│ 麦克风(16k)│──▶│ VAD │──▶│ ASR │──▶│ LLM 流式 │──▶│ 切分 │──▶│ 流式TTS│
└────────────┘   └─────┘   └─────┘   └──────────┘   └──────┘   └───────┘
                                          ▲                        │
                                          │                        ▼
                                    （backend 引擎）          队列播放(24k)
```

- **完整闭环**：麦克风 → VAD → ASR → LLM 流式 → 句级切分 → 流式 TTS → 队列播放 → 回声过滤 → 连续对话
- **依赖**：`backend/` 下的 `asr_engine / tts_engine / llm_engine / vad_engine`（延迟导入）
- **设计来源**：借鉴下载物象/乱七八糟中的 NachoBot、AIRI 研究报告（4 条纪律见 §5）

## 3. voice_chat_demo.py 框架

### 3.1 常量区
| 常量 | 值 | 用途 |
|---|---|---|
| SAMPLE_RATE | 16000 | ASR/VAD 采样率 |
| FRAME_SIZE | 1600 | 100ms/帧 |
| SILENCE_TIMEOUT | 8.0s | 单次录音上限 |
| MIN_SPEECH_DURATION | 0.3s | 最短有效语音段 |
| MIN_PENDING_SPEECH_DURATION | 0.2s | 播放期间插话最短长度 |
| ECHO_GAIN_RATIO | 1.6 | 音量遮蔽阈值（插话 RMS > AI播放×1.6） |
| ECHO_OVERLAP_RATIO | 0.6 | 防循环：文本字符重叠 >60% 判回声 |
| DEFAULT_TTS_ENGINE | qwen3-tts-customvoice | 默认本地 TTS 引擎 |

### 3.2 类与职责

| 类 | 职责 | 关键方法 |
|---|---|---|
| `LatencyTracker` | 各环节时间戳 + 延迟报告 | `mark(event)` / `report()` |
| `split_text_for_streaming()` | 句级切分（标点直断+短句合并+口语前缀粘连+md 残留剥离） | 纯函数 |
| `Recorder` | 流式录音 + VAD 状态机 + 插话采集 + 回声遮蔽 | `start/stop/set_paused/_callback/_flush_speech/_flush_pending_speech` |
| `Player` | 队列顺序播放 + 无缝缓冲 + barge-in 打断 + 音量上报 | `start/stop/enqueue/interrupt/_loop` |
| `VoiceChatDemo` | 主控：引擎加载 / 对话编排 / 历史管理 | 见 3.3 |

### 3.3 VoiceChatDemo 主控流程

```
main() → VoiceChatDemo(args) → load_engines()
                                    ├─ tts_manager.activate(引擎)   # 默认 qwen3-tts-customvoice
                                    ├─ ASR load_model(direct_gpu=True)
                                    └─ LLM 连接检查
            ├─ --text 模式 → run_text_mode(text)      # 跳过 ASR，验证 LLM+TTS
            └─ 语音模式   → run_voice_mode()          # 连续对话
```

### 3.4 一轮对话处理链（语音模式）

```
Recorder._callback（VAD 检测语音）
  → 语音段采集完成 → threading.Thread(_on_speech_end)
    → _handle_turn(audio)
      → ASR transcribe（mark asr_start/asr_done）
      → _generate_and_speak(text)   [asyncio]
          ├─ LLM generate_stream（mark llm_start/llm_first/llm_done）
          ├─ 句级切分 split_text_for_streaming(min=4)
          ├─ 每句 → asyncio task _synth_one（并行预合成，流式 chunk 入 play_queue）
          ├─ _play_dispatcher 按 seq 顺序把 chunk enqueue 到 Player
          └─ Player._loop 无缝播放（mark play_start/tts_done）
      → LatencyTracker.report() 输出延迟报告
```

### 3.5 并行预合成机制（核心优化）

- 每段句子独立 asyncio task 合成，LLM 出句即创建合成任务（不等上一段完成）
- `play_queue` 中 item 格式：`(seq, audio, sr, is_end)`
- `_play_dispatcher` 按 `seq` 顺序转发，保证播放顺序（乱序合成、顺序播放）
- 首片阈值 0.17s（4000 samples @24kHz），首片立即入队降低首句延迟
- 流式无产出时回退整段合成；中断时停止入队

### 3.6 barge-in / 回声过滤 / 插话机制

| 机制 | 实现 | 关键参数 |
|---|---|---|
| barge-in 打断 | `_gen_token` 令牌 +1 → 旧 LLM/TTS 任务 `interrupted()` 退出 | — |
| 音量遮蔽 | 播放期间用户 RMS 需 > AI 播放音量×1.6 才算插话 | ECHO_GAIN_RATIO=1.6 |
| 防循环 | 插话文本与刚播文本字符重叠 >60% 判回声丢弃 | ECHO_OVERLAP_RATIO=0.6 |
| 插话方案A | 播放期间不打断，插话排队（`_pending_segments`），播完再处理 | maxlen=8 |
| 预滚动缓冲 | 保留 1s 环形缓冲，防 ASR 丢开头字 | maxlen=10 帧 |
| 播放锁 | 播放期间 `Recorder.set_paused(True)` 暂停正常识别 | — |

### 3.7 线程/任务隔离

```
主线程      : 主循环（check_silence_timeout，50ms 轮询）
录音回调线程: Recorder._callback（VAD + 帧采集）
识别线程    : _on_speech_end → threading.Thread（ASR）
播放线程    : Player._loop（queue.Queue 解耦）
异步任务    : LLM 流式 / 并行 TTS 合成 / play dispatcher（asyncio）
锁          : _processing（同刻一句话）、_lock/_queue_lock/_buf_lock
```

## 4. demo_webui.py 框架

### 4.1 职责
- Flask 控制面板（port 5050），管理 `voice_chat_demo.py` 子进程
- SSE 实时日志推送 + 延迟报告解析 + 浏览器自动打开

### 4.2 API 一览
| 路由 | 方法 | 功能 |
|---|---|---|
| `/` | GET | 渲染 demo.html |
| `/api/start` | POST | 启动语音对话子进程（传 engine） |
| `/api/stop` | POST | 停止子进程（terminate→kill 兜底） |
| `/api/text` | POST | 文本模式测试（传 text+engine，运行完自动退出） |
| `/api/status` | GET | 查询子进程状态 |
| `/api/logs` | GET | SSE 实时日志流（先历史后实时+keepalive） |
| `/api/logs/clear` | POST | 清空日志缓冲 |
| `/api/latency` | GET | 从日志解析最近延迟报告（结构化） |

### 4.3 关键实现
- `_state` 全局状态（process/mode/engine/pid），`_lock` 互斥
- `_reader_thread` 后台读子进程 stdout → 环形缓冲 `_log_buffer`(maxlen 2000) → 推送 SSE 订阅者
- 子进程启动：`subprocess.Popen`（UTF-8 环境 + CREATE_NO_WINDOW）
- `_parse_latency_report()`：正则匹配延迟报告行（`_LATENCY_PATTERN`），找出最大延迟项/关键指标
- 退出清理：`atexit` + SIGBREAK/SIGINT 信号处理，确保子进程被杀

## 5. demo.html 框架（Web 控制台）

### 5.1 布局
```
header（标题 + 状态徽章）
├── 左面板（320px）
│   ├── TTS 引擎选择卡片（qwen3-tts-customvoice）
│   ├── 语音对话模式（启动 / 停止按钮）
│   ├── 文本模式测试（textarea + 发送按钮）
│   └── 操作（清空日志）
└── 右面板
    ├── 延迟追踪面板（关键指标卡片 + 各环节延迟条形图）
    └── 实时日志面板（暗色终端风格，级别着色 + 报告高亮）
```

### 5.2 前端逻辑
- SSE `EventSource("/api/logs")` 实时日志；行数上限 1000
- 延迟面板每 2s 轮询 `/api/latency`，渲染条形图（最大项红色标注）
- 日志着色：`[ERROR]/FAILED` 红、`[WARNING]/WARN` 橙、`[INFO]/✅/🔊/🎙` 蓝；延迟报告绿色、`★` 金色
- 进程退出日志 → 自动复位按钮状态

## 6. 借鉴的 4 条关键纪律（来自研究报告）

1. **句级切分 + 首段即触发 + 队列播放** → 低延迟流式
2. **回声过滤**（播放期间禁止识别，防自嗨）
3. **任务隔离**（录音/识别/播放分线程，队列解耦）
4. **LLM 只在关键节点介入**（ASR/LLM/TTS 各司其职）

## 7. 启动方式

```bat
start_demo.bat                     :: 一键启动 WebUI（http://127.0.0.1:5050）
python 对话DEMO/demo_webui.py      :: 等效启动
python 对话DEMO/voice_chat_demo.py :: 直接跑 CLI 语音对话（默认引擎）
```

## 8. 备注
- 本 DEMO 使用 Qwen3-TTS CustomVoice（音色固定 Vivian），首次启动需加载约 3.8GB 模型
- 语音模式下 Ctrl+C 退出会自动卸载 ASR/TTS/VAD 引擎
- 延迟报告关键指标：`★ 端到端(说完→听到)` 与 `★ 总响应(开口→听到)`

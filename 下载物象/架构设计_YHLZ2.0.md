===============================================================================
YHLZ 2.0 架构设计文档
===============================================================================
文档版本: v1.0
生成日期: 2026-08-01
项目定位: "元亨" 桌面AI语音伴侣 —— 云端大脑 + 本地轻量感官
一句话描述: 通过 WebUI 控制台统一托管 后端对话引擎 / Live2D桌宠 / 视觉听觉感知，
            实现"语音进 → AI答 → 语音出 + 口型表情同步"的完整陪伴体验。

------------------------------------------------------------------------------
一、设计目标与原则
------------------------------------------------------------------------------
1. 云端大脑 + 本地感官: LLM 走云端 API (DeepSeek/通义千问)，ASR/TTS/降噪/VAD
   等实时性敏感的模块跑在本地，兼顾智能上限与响应速度。
2. 模块化管理: 后端 6 大服务模块 (vision/asr/tts/vad/tools/llm) 可按需启停，
   避免无关模型常驻显存。
3. 低延迟语音链路: ASR 按 0.2 秒分片流式识别；LLM 流式输出与 TTS 合成并行
   (生产者/消费者队列)；音频播放线程集成口型同步。
4. 错峰运行: GPU 资源管理器在 ASR / TTS 之间轮换加载，单卡低显存可运行。
5. 可扩展: 三层扩展机制 —— 工具系统(内置)、智能工具管理器(LLM选工具)、
   插件系统(独立生命周期/事件总线/SDK)。
6. 安全可控: 沙盒白名单目录、防注入系统、插件独立隔离。

------------------------------------------------------------------------------
二、总体架构 (分层视图)
------------------------------------------------------------------------------
┌─────────────────────────────────────────────────────────────────────┐
│  启动层: start.py / start.bat / start_all.py / launcher.py          │
│          startup_manager.py / main_launcher.py / main_gui.py        │
│          (菜单选择 → 环境检查 → 进程编排 → 服务托管)                  │
└────────────────────────────┬────────────────────────────────────────┘
┌────────────────────────────┴────────────────────────────────────────┐
│  WebUI 控制台层 (webui_server.py, Flask :5000)                       │
│  进程托管(backend/live2d/avatar/asr/tts) + 配置 + 日志 + 代理转发     │
└───────────────┬─────────────────────────────────────────────────────┘
        ┌───────┴────────────────────────────────┐
┌───────┴────────┐                     ┌──────────┴────────┐
│  后端核心层      │  HTTP(REST/SSE)     │  桌宠/GUI 层       │
│  backend/       │◄──────────────────►│  desktop_avatar_*.py│
│  FastAPI :8000  │  WebSocket(zlib压缩)│  avatar_main.py     │
│  + 引擎模块群    │                     │  gui_main.py(5.1k行)│
└───────┬────────┘                     └──────────┬────────┘
        │                                        │
┌───────┴────────────────────────────────────────┴────────┐
│  支撑层                                                   │
│  ├─ 资源: assets/(Live2D模型/viewer/图标)                  │
│  ├─ 数据: data/ backend/data/(memories.db/personality.json)│
│  ├─ 模型: checkpoints/ sensevoice-finetuned/              │
│  │        whisper-finetuned-openai/ index-tts/ 下载物象/   │
│  ├─ 插件: plugins/(api_tools/file_tools/                  │
│  │        screen_monitor/utility_tools)                   │
│  ├─ 运行: logs/ recordings/ outputs/ memory/ venv/ cache/ │
│  └─ 扩展: updates/(直播插件更新包)                          │
└─────────────────────────────────────────────────────────────┘

外部依赖: DeepSeek API / 阿里云通义千问 API / Edge-TTS 在线服务 /
          VTube Studio(WebSocket) / B站直播弹幕 / HuggingFace 镜像(hf-mirror)

------------------------------------------------------------------------------
三、进程与端口规划
------------------------------------------------------------------------------
| 进程              | 技术      | 端口   | 职责                          |
|-------------------|-----------|--------|-------------------------------|
| backend/main.py   | FastAPI   | 8000   | 核心API + WebSocket + SSE     |
| webui_server.py   | Flask     | 5000   | 控制台/服务托管/代理           |
| Live2D预览服务器   | http.server| 8765  | assets/live2d 静态+viewer     |
| 桌宠内嵌Live2D    | http.server| 18765 | 桌宠窗口内Live2D渲染          |
| desktop_avatar/   | Node.js   | (可选) | 备用桌宠方案                  |

------------------------------------------------------------------------------
四、后端核心架构 (backend/)
------------------------------------------------------------------------------
4.1 分层结构
  API层   : main.py (FastAPI, 2475行) —— 路由/SSE/WebSocket/生命周期
  编排层   : conversation_manager / context_manager / smart_tool_manager /
            sync_manager / batch_processor
  引擎层   : llm_engine / asr_engine(_qwen) / tts_engine / vad_engine /
            voice_clone_engine / vision_engine / cognitive_engine
  音频层   : audio_buffer / audio_enhancer / echo_cancellation /
            noise_suppression / vad_engine
  记忆层   : memory / memory_v2 / personality / context_manager
  安全层   : sandbox / security
  支撑层   : gpu_manager / plugin_manager / plugin_sdk / tools /
            vts_client / bilibili_client / avatar_engine / config

4.2 生命周期 (lifespan 启动顺序)
  ① 日志/配置加载 → ② 按需加载ASR(模块管理) → ③ 注册GPU资源管理器 →
  ④ 初始化插件系统 → ⑤ 初始化智能工具管理器 → ⑥ 连续对话管理器启动 →
  ⑦ 音频播放线程(口型同步) → ⑧ 多模态同步管理器
  关闭: 播放线程 → 同步管理器 → ASR/TTS/VAD卸载 → GPU显存清理

4.3 通信协议
  - REST:  /chat /transcribe /synthesize /memory/* /tools/* /modules/* ...
  - SSE:   /chat (text/event-stream, {content}→{is_done})
  - WebSocket: /ws (简化版实时语音), /ws/stream (低延迟流式对话)
  - 压缩: CompressedWebSocket, zlib level=6, 阈值512B, 提供压缩率统计

4.4 核心数据流 (语音对话全链路)
  麦克风音频
    → echo_cancellation(回声消除) → noise_suppression(降噪)
    → vad_engine(VAD/打断) → asr_engine(识别, 0.2s分片流式)
    → context_manager(上下文) + memory(记忆检索) + personality(性格)
      + security(防注入) + smart_tool_manager(工具决策)
    → llm_engine(流式生成, SSE逐字推送)
    → tts_engine(并行合成, ≥12字符或标点切句)
    → audio_buffer → 播放线程 sd.play() → 每0.1s RMS口型
    → sync_manager(事件总线) → 桌宠 Live2D 口型/表情
  平行通道: vision_engine(屏幕/摄像头) → cognitive_engine(多模态认知) → 情绪驱动形象

4.5 模块管理 (错峰运行)
  - /modules/status|start|stop|gpu-clean
  - GPUResourceManager: 显存监控/清理; StaggeredRunner: ASR↔TTS轮换加载
  - 支持 FP16、KV Cache、torch.compile 三项性能优化

------------------------------------------------------------------------------
五、前端形态层 (桌宠/GUI)
------------------------------------------------------------------------------
| 脚本                  | 行数   | 说明                              |
|-----------------------|--------|-----------------------------------|
| desktop_avatar_py.py  | ~721   | 推荐稳定版: PyQt5透明窗+拖拽+托盘 |
| avatar_main.py        | ~992   | Windows API增强版: 分层透明+状态面板|
| desktop_avatar.py     | -      | 基础版                            |
| desktop_avatar_plus.py| -      | 带启动GUI版(:8765)                |
| live2d_desktop_avatar.py| -    | QWebEngineView版                  |
| gui_main.py           | 5147   | 大型管理GUI(Modern*组件库+多面板)  |
| gui_simple.py / main_gui.py / gui_floating_ball.py | - | 简化版/悬浮球 |
| desktop_avatar/       | Node.js| main.js + pet.html + preload.js    |

Live2D 渲染: assets/live2d/live2d_viewer.html (pixi-live2d-display)
模型: hiyori_vts(本地) + 在线模型(Hijiki/Shizuku/Miku, jsdelivr CDN)

------------------------------------------------------------------------------
六、数据与存储
------------------------------------------------------------------------------
| 类型     | 位置                      | 说明                        |
|----------|---------------------------|-----------------------------|
| 记忆     | backend/data/memories.db / memories.json / memories_v2.db | 语义检索+embedding |
| 性格     | backend/data/personality.json | 人设持久化                 |
| 配置     | .env / gui_config.json / launcher_config.json | 环境+界面+启动配置 |
| 日志     | logs/ backend.log          | 运行日志                    |
| 录音输出 | recordings/ outputs/      | 录音与生成物                |
| 模型权重 | checkpoints/(9.1GB) sensevoice-finetuned/ whisper-finetuned-openai/ index-tts/(26GB) 下载物象/(gpt.pth/s2mel.pth) | AI模型资源 |

------------------------------------------------------------------------------
七、配置体系 (.env → backend/config.py)
------------------------------------------------------------------------------
- API_PROVIDER: deepseek / dashscope (默认 dashscope)
- LLM: DEEPSEEK_API_KEY/BASE_URL/MODEL, DASHSCOPE_API_KEY/MODEL, VL_MODEL(视觉)
- ASR: ASR_MODEL(funasr-SenseVoiceSmall 默认 / qwen3-asr-1.7b / openai-whisper-*)
       ASR_MODE(speed/balanced/accuracy) + 高级参数(multi_pass/beam等)
- TTS: TTS_MODEL=edge-tts, TTS_PRECISION(fp16/bf16), TTS_MAX_CHUNK_LENGTH
- 性能: USE_FP16 / USE_KV_CACHE / STAGGERED_MODE / ASR_DEVICE / USE_TORCH_COMPILE
- 上下文: MAX_CONTEXT_TOKENS(8000) / SUMMARY_THRESHOLD(7000)
- 音频: SAMPLE_RATE(44100) / TTS_BUFFER_MS

------------------------------------------------------------------------------
八、扩展机制
------------------------------------------------------------------------------
1. 工具系统 (tools.py): ToolInfo/ToolRegistry/ToolExecutor, 内置计算器/天气/
   文件读写/网页搜索/时间/提醒, LLM可解析工具调用(parse_tool_call)
2. 智能工具管理器 (smart_tool_manager.py): ToolCallMode(auto/ask/manual),
   LLM分析用户意图 → 推荐/自动调用工具
3. 插件系统 (plugin_sdk.py + plugin_manager.py): 装饰器式声明
   (@neko_plugin/@plugin_entry/@lifecycle/@timer_interval/@message/@hook),
   Ok/Err 结果类型, 插件事件总线, 4类内置插件

------------------------------------------------------------------------------
九、技术栈汇总
------------------------------------------------------------------------------
后端: Python 3.11 / FastAPI / Uvicorn / Pydantic v2
AI  : OpenAI SDK(兼容层) / Transformers / Torch(FP16) / FunASR / Whisper
音频: librosa / sounddevice / soundfile / silero-vad / rnnoise / scipy / filterpy
前端: Flask(控制台) / PyQt5(桌宠/GUI) / Live2D Cubism(pixi.js) / HTML5
通信: HTTP + SSE + WebSocket(zlib压缩)
其他: python-dotenv / httpx / websockets / aiofiles / edge-tts

------------------------------------------------------------------------------
十、关键设计决策与取舍
------------------------------------------------------------------------------
| 决策点              | 选择                      | 理由                        |
|--------------------|---------------------------|-----------------------------|
| LLM 部署方式        | 云端API                   | 本地显存不足, 云端智能上限高 |
| ASR 引擎            | FunASR SenseVoice 默认    | 中文效果好+本地可跑          |
| TTS 引擎            | Edge-TTS 在线             | 免费+音色多+无需GPU          |
| 播放策略            | 2秒累积播放(零等待待优化)  | 减少播放卡顿                 |
| 通信压缩            | zlib(阈值512B)            | 音频帧数据量大, 省带宽       |
| 模型加载            | 按需+错峰                  | 低显存显卡友好               |

===============================================================================
附: 相关文档
- 项目结构白皮书_YHLZ2.0.md  (目录级结构盘点)
- 功能模组清单_YHLZ2.0.md    (逐模块功能明细)
- 改进蓝图_YHLZ2.0_v1.0.md   (演进路线)
- 学习笔记_NEKO/NachoBot研究报告.md (对标研究)
===============================================================================

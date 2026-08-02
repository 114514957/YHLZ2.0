================================================================================
YHLZ 2.0 项目结构白皮书
================================================================================
文档版本: v1.0
生成日期: 2026-07-31
项目定位: "元亨" 桌面AI语音伴侣 —— 云端大脑 + 本地轻量感官
技术栈  : Python 3.x + FastAPI + Flask + PyQt5 + Live2D + VTS + Edge-TTS
架构模式: 单体代码库 + 多进程服务（后端/WebUI/桌宠）+ 模块化引擎层

--------------------------------------------------------------------------------
一、总体架构
--------------------------------------------------------------------------------
                    ┌─────────────────────────────────────┐
                    │          启动层 (launcher)          │
                    │  start.py / start.bat / start_all   │
                    │  launcher.py / startup_manager.py   │
                    └───────────────┬─────────────────────┘
                    ┌───────────────┴─────────────────────┐
                    │         WebUI 控制台 (Flask)        │
                    │  webui_server.py :5000 服务管理器   │
                    │  进程托管: backend/live2d/avatar    │
                    └───────────────┬─────────────────────┘
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────┴────────┐         ┌────────┴────────┐         ┌────────┴────────┐
│  后端核心       │         │  桌宠/GUI       │         │  前端页面       │
│  backend/      │◄───────►│  desktop_avatar │◄───────►│  webui_static/ │
│  FastAPI :8000 │  HTTP/WS │  *_py.py       │         │  webui_templat │
│  WebSocket+SSE │         │  gui_main.py    │  HTTP   │  es/           │
└───────┬────────┘         │  5.1k行 PyQt    │         └────────────────┘
        │                  └───────┬────────┘
        │                   (Live2D 内嵌HTTP :18765 / :8765)
        │
        ├── 资源层: assets/(live2d模型/图标)
        ├── 数据层: data/ backend/data/(memories.db/personality.json)
        ├── 模型层: checkpoints/ sensevoice-finetuned/ whisper-finetuned-openai/
        │           index-tts/ 下载物象/ cache/(已清理)
        ├── 插件层: plugins/(api_tools/file_tools/screen_monitor/utility_tools)
        ├── 运行层: logs/ recordings/ outputs/ memory/ venv/
        └── 扩展层: updates/live_stream/(B站直播插件更新包)

--------------------------------------------------------------------------------
二、后端模块详解 (backend/, FastAPI, 端口8000)
--------------------------------------------------------------------------------
■ 入口 backend/main.py (约2000行)
  - lifespan 生命周期: 模块管理模式(ASR按需加载) → 注册GPU资源管理器 →
    插件系统 → 智能工具管理器 → 连续对话管理器 → 音频播放线程 → 同步管理器
  - CompressedWebSocket: zlib压缩(阈值512B) + 压缩统计
  - ConnectionManager: 连接池管理
  - 音频播放线程 _audio_player_loop: 累积2秒音频→sd.play()→
    每0.1秒计算RMS→sync_manager.record_event('mouth_sync')→口型同步
  - API 分组:
    * 对话:  /chat(SSE流式+工具决策+TTS并行) /transcribe /synthesize
             /synthesize/stream /interrupt /clear-history
    * 智能工具: /tools /tools/categories /tools/{name} /tools/recommend
             /tools/call /tools/history /tools/analyze /tools/list
             /tools/prompt /tools/logs /tools/execute
    * 性格:   /personality(GET/POST/reset)
    * 记忆库: /memory(CRUD/search/list/clear/stats/iterate/prune)
             /memory/pledge(誓约: add/active/complete)
             /memory/{id}/relation(关联) /memory/scenario(情景)
             /memory/consolidate(摘要合并)
    * 沙盒:   /sandbox/stats/logs/directories(+增删白名单)
    * Live2D: /live2d(页面/status/load/action/emotion/emotion-intensity)
    * 系统:   /health /websocket-stats /cache-stats /modules/*
  - /chat 数据流: 智能工具决策 → 上下文注入 → LLM流式生成 →
    TTS生产者(累积≥12字符或≥6字符+标点才合成) → audio_buffer →
    播放线程(口型同步) → SSE推送 {content,is_done}

■ 引擎层 (backend/*.py)
  - config.py (138行): .env配置, API_PROVIDER(deepseek/dashscope),
    ASR模型选择(qwen3-asr/whisper/funasr), FP16/KV缓存/错峰开关
  - llm_engine.py (423行): LLMEngine — DeepSeek/通义API客户端,
    带缓存(_generate_cache_key/_set_cached_response)
  - llm_engine_ollama.py (535行): OllamaEngine/OllamaManager — 本地模型
  - asr_engine.py (1081行): ASREngine — 多引擎调度
    * load_model/_init_funasr_model/_init_whisper_model/_check_cuda
    * transcribe/_transcribe_funasr/_transcribe_whisper
    * _transcribe_with_multi_pass(多遍校验) / transcribe_batch(批处理)
    * _audio_preprocessing/_noise_gate/_dynamic_range_compression
    * start_streaming/stream_audio/callback/get_stream_result(流式识别)
    * _select_hf_endpoint/_test_hf_endpoint(镜像自动选择)
  - asr_engine_qwen.py (300行): Qwen3ASREngine — Qwen3-ASR-1.7B
  - tts_engine.py (484行): TTSEngine — Edge-TTS在线
    * _smart_chunk_text(智能切句) / synthesize / stream_synthesize
    * _synthesize_sync_wrapper / _get_mock_audio(降级)
    * get_available_voices(音色列表)
  - vad_engine.py (282行): VADEngine — Silero VAD
  - audio_buffer.py (243行): AudioBufferManager — 音频缓冲+打断+
    calculate_mouth_open(口型RMS计算)
  - conversation_manager.py (355行): 连续对话编排(ASR→LLM→TTS→VAD),
    _build_system_prompt/_build_messages/_extract_keywords
  - context_manager.py (372行): 上下文+token计数+缓存+性格管理+
    记忆路由+情绪记录(add_emotion_record/get_emotion_trend)
  - memory.py (1060行): MemoryManager — 记忆库
    * add_memory/get_memory/search_memories(语义检索+embedding)
    * extract_from_dialogue(对话抽取: 用户信息/事件/偏好)
    * add_pledge誓约/complete_pledge/get_active_pledges
    * add_memory_relation关联 / add_context_scenario情景
    * summarize_and_consolidate(摘要合并) / prune_expired_memories(遗忘)
  - memory_v2.py (1137行): MemoryManagerV2 — 升级版
    EmotionState/ShortTermMemory/LongTermMemoryEntry/Contact/
    MemoryRelation/KnowledgeGraph(知识图谱)/PersonalityProfile
  - cognitive_engine.py (492行): CognitiveEngine — 认知状态机
    TensionType(张力)/CognitiveState/VisionInput/AudioInput/
    ThinkingInput/CognitiveOutput(多模态认知融合)
  - vision_engine.py (378行): VisionEngine — 屏幕/摄像头
    * start_screen_capture/capture_frame/capture_optimized_frame
    * detect_objects/analyze_scene/generate_description(VL模型)
    * _denoise/_enhance/_sharpen/_adjust_contrast(图像优化)
  - vts_client.py (651行): VTSClient — VTube Studio 联动
    (认证token/表情VTSExpression/触发器VTSTriggerType/API控制)
  - voice_clone_engine.py (198行): VoiceCloneEngine — 声音克隆
  - sync_manager.py (227行): SyncManager — 多模态同步事件总线
    SyncEvent/record_event/_handle_mouth_sync/_handle_emotion_change/
    _handle_speech_start/End/_handle_tts_chunk(口型/情绪/语音事件分发)
  - avatar_engine.py (447行): AvatarEngine — 形象状态机
    AvatarExpression/AvatarGesture/AvatarState
  - gpu_manager.py (222行): GPUResourceManager/StaggeredRunner —
    显存管理+错峰运行(ASR/TTS轮换加载)
  - echo_cancellation.py (548行): AEC — AdaptiveEchoCanceller/
    FrequencyDomainEchoCanceller/EchoSuppression/AECProcessor
  - noise_suppression.py (427行): 降噪 — AGC/NoiseReduce/
    SpectralSubtraction/AudioEnhancer
  - audio_enhancer.py (571行): AudioEnhancer — 音频增强
  - batch_processor.py (565行): 批处理 — AudioTask/BatchResult/
    ASRBatchProcessor/TTSBatchProcessor/AudioPipeline/StreamBuffer
  - bilibili_client.py (69行): BilibiliClient — B站接口
  - text_postprocessor.py (671行): TextPostProcessor — 文本后处理
  - personality.py (109行): PersonalityConfig/Manager — 性格配置
  - security.py (216行): AntiInjectionSystem — 防注入
  - tools.py (754行): ToolInfo/ToolRegistry/ToolExecutor — 工具系统
  - sandbox.py (487行): AgentSandbox — 沙盒(白名单目录/操作日志)
  - smart_tool_manager.py (436行): SmartToolManager — LLM智能选工具
    ToolCallMode(auto/ask/manual)/ToolRecommendation/ToolCallResult
  - plugin_manager.py (531行): PluginManager — 插件生命周期管理
  - plugin_sdk.py (721行): 插件SDK — PluginContext/PluginEntry/
    LifecycleHandler/PluginBus/PluginMemoryClient/NekoPluginBase

■ 插件系统 (plugins/, 4类)
  - api_tools/     API工具
  - file_tools/    文件工具
  - screen_monitor/ 屏幕监控(截图间隔/分析间隔/自动对话)
  - utility_tools/ 通用工具

--------------------------------------------------------------------------------
三、桌宠/虚拟形象 (前端形态层)
--------------------------------------------------------------------------------
■ desktop_avatar_py.py (721行) — 推荐稳定版 PyQt5桌宠
  - AvatarWindow: 透明窗口+拖拽+缩放+右键菜单+系统托盘
  - _init_live2d_server: 内置Live2D HTTP服务器(:18765, live2d_viewer.html)
  - _init_win_api: Windows API透明/置顶(_make_children_transparent)
  - 口型同步: 音频播放时RMS → Live2D ParamMouthOpen
  - 表情: _set_emotion / 位置记忆(_save/_restore_position)
  - show_animation 加载动画 / ConsoleWebPage(QWebEngine调试)
■ avatar_main.py (992行) — Windows API增强版
  - AvatarWindow: 分层窗口(完全透明背景)+全屏自由拖动+滚轮缩放
  - StatusPanel(状态气泡: 延迟/CPU/内存/服务状态)
  - ChatDialog(双击打开对话框)
  - LoadingWindow 加载中
■ desktop_avatar.py / desktop_avatar_plus.py / live2d_desktop_avatar.py
  - 变体: 基础版 / 带启动GUI版(:8765) / QWebEngineView版
■ win_api_avatar.py — Windows API模块(透明/置顶/拖拽/动画)
■ gui_main.py (5147行) — 大型管理GUI
  - Modern* 组件库(Button/GroupBox/TabWidget等)
  - 面板: ServiceSettings/ASR/TTS/LLM/GPU/Memory/Personality/Vision/
    Avatar/TextChat/VoiceChat/Tools
  - MainWindow 主窗口
■ gui_simple.py / main_gui.py / gui_floating_ball.py — 简化版/悬浮球
■ desktop_avatar/ (Node.js版): main.js/pet.html/preload.js/start.bat
■ assets/: icon.png + live2d/(模型+viewer)

--------------------------------------------------------------------------------
四、WebUI 控制台 (webui_server.py, Flask, 端口5000)
--------------------------------------------------------------------------------
- 服务托管: backend(:8000) / live2d / avatar / asr / tts 的启停+状态
- API 路由:
  * /api/status 服务状态 | /api/services/<name>/start|stop|restart
  * /api/services/start_all|stop_all
  * /api/avatar/start|stop|status|control|open_live2d
  * /api/logs(backend) /api/logs/clear
  * /api/memory/clear|stats
  * /api/config 配置读写 | /api/chat 转发 | /api/health
  * /api/system/info | /api/benchmark/pcm(延迟测试,引pcm_latency_test)
  * /api/tech/comparison | /api/shutdown
- webui_templates/index.html + webui_static/(前端资源)

--------------------------------------------------------------------------------
五、启动链路
--------------------------------------------------------------------------------
■ start.py — 交互菜单: 1.WebUI 2.WebUI+桌宠 3.停止 4.状态 5.桌宠 6.浏览器
■ start.bat — 一键: backend/main.py + avatar_main.py + webui_server.py
■ start_all.bat / start_webui.bat / start_avatar_py.bat — 分项启动
■ launcher.py (382行) — 通用启动器: 环境检查/端口检查/进程管理/日志,
  --simple 用 gui_simple.py, 否则 gui_main.py
■ startup_manager.py (284行) — StartupManager: 预启动检查/服务编排
■ start_backend.py 已删除(清理) | start_live2d_server.py 已删除
■ 环境: .env(API密钥) / .env.example / gui_config.json / launcher_config.json

--------------------------------------------------------------------------------
六、数据与资源
--------------------------------------------------------------------------------
■ backend/data/: memories.db / memories.json / memories_v2.db /
  personality.json (记忆+性格持久化)
■ data/ test_sandbox.txt (沙盒测试)
■ checkpoints/ 9.1GB: hf_cache/ qwen0.6bemo4-merge/ (模型权重)
■ sensevoice-finetuned/ whisper-finetuned-openai/: 微调模型
■ index-tts/ 26GB: 独立IndexTTS2项目(含独立venv, TTS引擎)
■ 下载物象/: gpt.pth/s2mel.pth/torch-2.6.0+cu124.whl/akari(Live2D模型)
■ logs/ 运行时日志 | recordings/ outputs/ 录音输出 | memory/ GUI记忆
■ updates/live_stream/: 直播插件更新(B站/事件/TTS/口型同步/话题生成)
■ vts_auth_token.txt: VTS认证token(backend/vts_client.py依赖)

--------------------------------------------------------------------------------
七、核心数据流 (语音对话完整链路)
--------------------------------------------------------------------------------
麦克风 → 回声消除(echo_cancellation) → 降噪(noise_suppression)
  → VAD检测(vad_engine) → ASR识别(asr_engine/audio_buffer)
  → 上下文+记忆+性格注入(context_manager/memory/personality)
  → LLM生成(llm_engine, 工具调用tools/smart_tool_manager)
  → 文本流式 → TTS合成(tts_engine, smart_chunk切句)
  → audio_buffer → 播放线程sd.play()
  → sync_manager(mouth_sync事件) → 桌宠Live2D口型/表情
  ↔ 平行: vision_engine(屏幕/摄像头感知) → cognitive_engine(多模态认知)

--------------------------------------------------------------------------------
八、配置体系 (.env → backend/config.py)
--------------------------------------------------------------------------------
- API_PROVIDER: deepseek / dashscope (默认dashscope)
- DEEPSEEK_*/DASHSCOPE_API_KEY/MODEL, VL_MODEL(视觉)
- ASR_MODEL: funasr-iic/SenseVoiceSmall(默认) / qwen3-asr-1.7b /
  openai-whisper-*; ASR_MODE(speed/balanced/accuracy)
- ASR高级: beam_size/best_of/patience/temperature/multi_pass/
  audio_enhancement/text_postprocessing/fast_mode
- TTS_MODEL: edge-tts; TTS_PRECISION(fp16/bf16); TTS_MAX_CHUNK_LENGTH
- USE_FP16 / USE_KV_CACHE / STAGGERED_MODE(错峰) / ASR_DEVICE(cuda)
- MAX_CONTEXT_TOKENS(8000) / SUMMARY_THRESHOLD(7000)
- SAMPLE_RATE(44100) / TTS_BUFFER_MS

--------------------------------------------------------------------------------
九、规模统计 (2026-07-31 清理后)
--------------------------------------------------------------------------------
根目录文件: 31 | 目录: 21 | backend模块: 34个 .py
代码量Top: gui_main.py(5147行) > backend/main.py(~2000行) >
asr_engine.py(1081) > memory.py(1060) > memory_v2.py(1137) >
tts_engine.py(484) 等, 后端总约2万行
磁盘占用: index-tts(26GB) > checkpoints(9.1GB) > venv > 微调模型

--------------------------------------------------------------------------------
十、已知技术债 (对比成熟项目后的自我审视, 详见学习笔记)
--------------------------------------------------------------------------------
1. 口型同步粗糙: 0.1秒chunk RMS, 无LIPSYNC参数保护/差分淡出/基线快照
2. TTS单引擎: 仅Edge-TTS, 无多provider抽象/回退/情绪音色映射
3. 说话延迟: 播放线程累积2秒才播, 无"首段就绪即开口"零等待
4. 无主动陪伴状态机: 有screen_monitor但无活动分类/话题权重/防复读
5. 记忆无事实抽取/反思综合/遗忘衰减(有誓约/关联/情景)
6. 无情绪引擎: 无外显表情LLM通道/内隐用户情绪追踪
7. 桌宠通信无版本化协议/心跳PING/PONG
8. 上下文管理器无流式对话专用管线, /chat与conversation_manager双轨

--------------------------------------------------------------------------------
附: 相关文档
--------------------------------------------------------------------------------
- 学习笔记_NEKO研究报告.md     (N.E.K.O猫娘: TTS/Realtime/口型/主动陪伴/记忆)
- 学习笔记_NachoBot研究报告.md  (NachoBot: GPT-SoVITS/Live2D/誓约/沙盒)
- 下载物象/: 模型资源(gpt.pth/s2mel.pth/akari Live2D)
================================================================================

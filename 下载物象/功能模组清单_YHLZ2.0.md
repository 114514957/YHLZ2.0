===============================================================================
YHLZ 2.0 功能模组清单
===============================================================================
文档版本: v1.0
生成日期: 2026-08-01
说明: 按"入口/核心引擎/音频/记忆认知/安全扩展/前端/工具链"分组，
      逐模块列出职责、关键类/函数与对外接口。行数基于当前代码核对。

------------------------------------------------------------------------------
A. 入口与启动组
------------------------------------------------------------------------------
■ start.py (119行) — 交互式启动器
  菜单: 1.WebUI | 2.WebUI+桌宠 | 3.停止全部 | 4.检查状态 | 5.仅桌宠 | 6.开浏览器
  关键: get_python(优先venv), check_webui_running(端口5000探测), open_browser

■ launcher.py / main_launcher.py — 通用启动器
  main_launcher.ServiceManager: 服务编排(backend/Live2D/audio/vision/VTS/bilibili)
  LauncherConfig: launcher_config.json 读写(port/host/模型名/悬浮球位置/主题)
  启动结果✅❌汇总; stop_all 统一回收

■ startup_manager.py (284行) — StartupManager: 预启动检查 + 服务编排
■ start.bat / start_all.bat / start_webui.bat / start_avatar_py.bat — 一键脚本
■ main_gui.py / create_shortcut.py — GUI入口/快捷方式

------------------------------------------------------------------------------
B. 核心引擎组 (backend/)
------------------------------------------------------------------------------
■ llm_engine.py (399行) — LLMEngine: DeepSeek/通义千问API客户端
  - is_connected / connect / disconnect / generate_stream(流式) /
    generate_stream_with_image(多模态) / 响应缓存(_generate_cache_key)
■ llm_engine_ollama.py (522行) — OllamaEngine/OllamaManager: 本地离线LLM
■ asr_engine.py (1065行) — ASREngine: 多引擎调度(FunASR/Whisper)
  - load_model/_init_funasr_model/_init_whisper_model/_check_cuda
  - transcribe / _transcribe_with_multi_pass(多遍校验) / transcribe_batch
  - _audio_preprocessing/_noise_gate/_dynamic_range_compression
  - start_streaming/stream_audio/get_stream_result(流式识别)
  - _select_hf_endpoint/_test_hf_endpoint(HF镜像自动选择)
■ asr_engine_qwen.py (293行) — Qwen3ASREngine: Qwen3-ASR-1.7B
  FP16混合精度 + KV Cache + 错峰注册
■ tts_engine.py (474行) — TTSEngine: Edge-TTS在线合成
  - _smart_chunk_text(智能切句≤50字) / synthesize / stream_synthesize_text
  - _synthesize_sync_wrapper / _get_mock_audio(降级兜底) / get_available_voices
■ vad_engine.py (257行) — VADEngine: 语音活动检测
  - detect_speech / get_config / set_config / 打断开关(interrupt_enabled)
  - 纯能量检测(简化版) + 配合SenseVoice内置VAD
■ voice_clone_engine.py (191行) — VoiceCloneEngine: 声音克隆
  - load_reference_audio / load_reference_audio_from_array / clone_voice
  - set_voice / get_available_voices / clear_reference
■ vision_engine.py (373行) — VisionEngine: 视觉感知
  - VisionMode(摄像头/屏幕) / ImageOptimization(denoise/enhance/sharpen/contrast)
  - start_camera / start_screen_capture / capture_frame /
    capture_optimized_frame / analyze_scene / generate_description(VL模型)
■ cognitive_engine.py (482行) — CognitiveEngine: 多模态认知状态机
  - TensionType(张力) / CognitiveState / VisionInput / AudioInput /
    ThinkingInput / CognitiveOutput
  - process(融合视觉/音频/思考) / detect_emotion(文本情感) /
    control_avatar_by_emotion / control_avatar_by_text(驱动形象)
■ avatar_engine.py (436行) — AvatarEngine: 形象状态机
  - AvatarExpression / AvatarGesture / AvatarState(形象表达管理)

------------------------------------------------------------------------------
C. 音频链路组 (backend/)
------------------------------------------------------------------------------
■ audio_buffer.py (236行) — AudioBufferManager
  - add_audio(入队) / get_next_audio(出队) / interrupt(打断) /
    clear_buffer / calculate_mouth_open(RMS口型值) / reset_mouth_open
■ echo_cancellation.py (531行) — AEC: 自适应回声消除
  - AdaptiveEchoCanceller / FrequencyDomainEchoCanceller /
    EchoSuppression / AECProcessor
■ noise_suppression.py (408行) — 降噪
  - AGC(自动增益) / NoiseReduce / SpectralSubtraction(谱减法) / AudioEnhancer
■ audio_enhancer.py (566行) — AudioEnhancer: 音频增强管道
■ batch_processor.py (545行) — 批处理
  - AudioTask / BatchResult / ASRBatchProcessor / TTSBatchProcessor /
    AudioPipeline / StreamBuffer (吞吐优化)
■ text_postprocessor.py (666行) — TextPostProcessor: ASR文本后处理
  (中文修正/标点恢复等)

------------------------------------------------------------------------------
D. 对话/上下文/记忆组 (backend/)
------------------------------------------------------------------------------
■ conversation_manager.py (345行) — ConversationManager: 连续对话编排
  - ConversationState(空闲/聆听/思考/说话)
  - set_engines(ASR/LLM/TTS/VAD/缓冲) / start_conversation
  - _build_system_prompt / _build_messages / _extract_keywords
■ context_manager.py (362行) — ContextManager: 上下文管理
  - add_message / get_context / token计数 / 超限压缩(summary)
  - 性格管理(update_personality) / 记忆路由 / 情绪记录(add_emotion_record)
■ personality.py (101行) — PersonalityConfig/PersonalityManager: 性格人设
  (名称/性别/年龄/职业/性格特质/说话风格/口头禅)
■ memory.py (1050行) — MemoryManager: 记忆库 v1
  - add_memory / search_memories(embedding语义检索) /
    extract_from_dialogue(对话抽取用户信息/事件/偏好)
  - add_pledge誓约 / complete_pledge / get_active_pledges
  - add_memory_relation关联 / add_context_scenario情景注入
  - summarize_and_consolidate(摘要合并) / prune_expired_memories(遗忘)
■ memory_v2.py (1068行) — MemoryManagerV2: 记忆库 v2 (升级版)
  - EmotionState / ShortTermMemory / LongTermMemoryEntry / Contact /
    MemoryRelation / KnowledgeGraph(知识图谱) / PersonalityProfile

------------------------------------------------------------------------------
E. 安全与扩展组 (backend/)
------------------------------------------------------------------------------
■ security.py (206行) — AntiInjectionSystem: 防注入
  - 输入归一化 / 指令锚定 / 语义检测 / 输出验证(InjectionResult)
■ sandbox.py (473行) — AgentSandbox: 安全沙盒
  - SandboxConfig(白名单目录) / SandboxOperation(操作日志)
  - add/remove_allowed_directory / get_stats / 文件操作受限执行
■ tools.py (705行) — 工具系统
  - ToolInfo / ToolRegistry / ToolExecutor(注册+执行+日志)
  - 内置工具: calculator_tool / weather_tool / read_file_tool /
    write_file_tool / list_files_tool / web_search_tool /
    get_time_tool / get_date_tool / set_reminder_tool
  - get_tool_prompt / parse_tool_call / format_tool_result
■ smart_tool_manager.py (364行) — SmartToolManager: LLM智能选工具
  - ToolCallMode(auto/ask/manual) / ToolRecommendation / ToolCallResult
  - decide_and_call(意图分析→推荐→调用) / get_recommendations /
    get_call_history
■ plugin_manager.py (405行) — PluginManager: 插件生命周期
  - discover_plugins / load_all_plugins / start/stop/restart/reload
  - call_entry / get_all_entries / get_entry_tool_prompt
■ plugin_sdk.py (583行) — 插件SDK
  - 装饰器: @neko_plugin / @plugin_entry / @lifecycle / @timer_interval /
    @message / @hook
  - Ok/Err 结果类型 / PluginContext / LifecycleHandler / TimerTask /
    PluginBus(事件总线) / PluginMemoryClient / NekoPluginBase

■ 内置插件 (plugins/)
  - api_tools/      API调用工具 (2.4KB)
  - file_tools/     文件读写工具 (3.2KB)
  - screen_monitor/ 屏幕监控(截图/分析间隔/自动对话) (11KB)
  - utility_tools/  通用工具 (2.6KB)

------------------------------------------------------------------------------
F. 多模态同步与外部联动组 (backend/)
------------------------------------------------------------------------------
■ sync_manager.py (218行) — SyncManager: 同步事件总线
  - SyncEvent / record_event / get_recent_events
  - 事件类型: mouth_sync(口型) / emotion_change(表情) /
    speech_start/end / tts_chunk
■ vts_client.py (640行) — VTSClient: VTube Studio 联动
  - 认证(WebSocket + vts_auth_token.txt) / 模型列表与加载
  - VTSExpression(表情) / VTSTriggerType(触发器) / API控制
■ bilibili_client.py (62行) — BilibiliClient: B站直播弹幕接入
■ gpu_manager.py (212行) — GPU资源管理
  - GPUResourceManager(显存监控/clear_gpu_memory) /
    StaggeredRunner(错峰运行: ASR↔TTS轮换)
■ avatar_engine.py — 见 B 组(形象状态机, 供VTS/Live2D驱动)

------------------------------------------------------------------------------
G. WebUI 控制台 (webui_server.py, Flask :5000)
------------------------------------------------------------------------------
■ 服务托管: backend/live2d/avatar 启停 + 状态 + 端口检测(kill_port_process)
■ 路由分组:
  - 状态: /api/status /api/health /api/system/info /api/logs(clear)
  - 服务: /api/services/start|stop|restart /api/services/start_all|stop_all
  - 桌宠: /api/avatar/start|stop|status|control /api/avatar/open_live2d
  - 数据: /api/memory(list/add/delete/stats/clear) /api/personality
  - 工具: /api/tools/list /api/tools/call
  - 代理: /api/vision/<endpoint> /api/live2d/<endpoint> /api/tts/synthesize
         /api/asr/transcribe /api/chat /api/chat_stream(SSE转发)
  - 系统: /api/config(GET/SAVE) /api/benchmark/pcm(延迟测试)
         /api/tech/comparison /api/shutdown

------------------------------------------------------------------------------
H. 桌宠/GUI 组
------------------------------------------------------------------------------
■ desktop_avatar_py.py (~721行) — 推荐稳定版 PyQt5 桌宠
  - AvatarWindow: 透明窗口 / 拖拽 / 滚轮缩放 / 右键菜单 / 系统托盘
  - 内嵌Live2D服务器(:18765) / Windows API透明置顶 / 口型同步 / 表情 /
    位置记忆 / 加载动画
■ avatar_main.py (~992行) — Windows API 增强版
  - 分层窗口(全透明背景) / 状态气泡面板(延迟/CPU/内存/服务状态) /
    双击对话窗 / LoadingWindow
■ desktop_avatar.py / desktop_avatar_plus.py / live2d_desktop_avatar.py
  - 基础版 / 带启动GUI(:8765) / QWebEngineView版
■ win_api_avatar.py — Windows API 模块(透明/置顶/拖拽/动画)
■ gui_main.py (5147行) — 大型管理GUI
  - Modern* 组件库(Button/GroupBox/TabWidget等)
  - 面板: ServiceSettings / ASR / TTS / LLM / GPU / Memory / Personality /
    Vision / Avatar / TextChat / VoiceChat / Tools
■ gui_simple.py / gui_floating_ball.py — 简化版/悬浮球
■ desktop_avatar/ (Node.js): main.js / pet.html / preload.js / start.bat

------------------------------------------------------------------------------
I. 后端API总览 (backend/main.py, FastAPI :8000)
------------------------------------------------------------------------------
■ 对话:  POST /chat(SSE流式+工具+TTS并行)  POST /transcribe
         POST /synthesize(/stream)  POST /interrupt  POST /clear-history
■ 流式WS: WS /ws(简化语音)  WS /ws/stream(低延迟: ASR分片+LLM流+TTS流)
■ 工具:   GET /tools(/list//categories/{name}/prompt/logs/history)
          POST /tools/recommend|call|execute|analyze
■ 性格:   GET/POST /personality  POST /personality/reset
■ 记忆:   POST /memory(GET list/search/delete/update/clear/stats/iterate/prune)
          /memory/pledge(add/active/complete) /memory/{id}/relation
          /memory/scenario(match/context-prompt) /memory/consolidate
■ 沙盒:   GET /sandbox/stats|logs|directories  POST/DELETE /sandbox/directory
■ VAD:    GET/POST /vad/config  POST /vad/detect  POST /vad/interrupt
■ 声音克隆: /voice-clone/status|voices|set-voice|load-reference|synthesize|clear
■ TTS引擎:  POST /tts/engine(切换)  GET /tts/engines
■ 视觉:   /vision/status|cameras|monitors|start|start-screen|stop|capture|
          optimization|analyze|history|reset
■ Live2D: /live2d(page/status/models/load/action/emotion/emotion-intensity/
          emotion-text/mouth-open/glow-color)
■ 同步:   GET /sync/status|events
■ 插件:   GET /plugins(/entry/prompt/discover/reload-all)
          POST /plugins/{id}/start|stop|restart|reload|execute
■ 模块:   GET /modules/status  POST /modules/start|stop|gpu-clean
■ 认知:   GET /cognitive/status  POST /cognitive/process|reset|tension
■ 系统:   GET /health /websocket-stats /cache-stats  (Swagger: /docs, /redoc)

------------------------------------------------------------------------------
J. 功能覆盖矩阵 (能力 vs 模块)
------------------------------------------------------------------------------
| 能力             | 主模块                    | 辅助模块                   |
|------------------|---------------------------|----------------------------|
| 语音识别         | asr_engine(+qwen)         | vad/降噪/回消/后处理        |
| 语音合成         | tts_engine                | audio_buffer/播放线程       |
| 智能对话         | llm_engine                | context/记忆/性格/防注入    |
| 工具调用         | smart_tool_manager        | tools/sandbox/plugins       |
| 视觉理解         | vision_engine             | llm(VL模型)/cognitive      |
| 记忆与情感       | memory(+v2)/personality   | cognitive/context          |
| 形象驱动         | avatar_engine/vts_client  | sync_manager/cognitive     |
| 直播联动         | bilibili_client           | updates/live_stream        |
| 管理控制         | webui_server/gui_main     | main_launcher/startup      |
| 本地LLM(可选)    | llm_engine_ollama         | Ollama                     |

===============================================================================

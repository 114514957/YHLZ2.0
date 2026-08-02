========================================================================
N.E.K.O 猫娘计划 研究报告（学习笔记）
仓库: https://github.com/Project-N-E-K-O/N.E.K.O  (Apache-2.0, 2.3k stars)
=======================================================================
特性: 主动陪伴/实时语音(Realtime API)+文字/五维记忆/多形态Avatar(Live2D/
VRM/MMD/PNGTuber/猫咪桌宠)/Agent工具/插件生态/14+AI服务商/Steam创意工坊
技术栈: Python 3.11 + FastAPI + 原生JS前端 + Electron桌宠

==========================================================
一、TTS 语音合成 (main_logic/tts_client/)
==========================================================
1. 三类 Provider 架构 (_registry_meta.py):
   - ws_bistream (step/qwen/cosyvoice): 文本碎片一到即推WebSocket, 客户端
     不切句, 延迟最低
   - http_sentence (cogtts/gemini/openai/custom/minimax): SentenceBuffer
     按标点切句, _non_bistream_tts_main_loop + _run_sentence_tts_worker
   - local (gptsovits/local_cosyvoice): 独立实现 workers/gptsovits.py
   支持: cosyvoice/minimax/elevenlabs/gptsovits/gemini/step/grok/vllm_omni

2. 流式收尾协议 (_infra.py):
   - TTS_AUDIO_DONE_SENTINEL = "__audio_done__": 前端把它当作口型同步收尾
     的权威信号; 被中断的语音不发该信号(前端据此不误复位口型)
   - SentenceBuffer / _AudioQueueProxy 负责句子缓冲与队列代理
   - 音频统一经 soxr 重采样

3. 运行时 (core/tts_runtime.py, TtsRuntimeMixin):
   - _start_tts_thread/_respawn_tts_worker: worker线程全生命周期管理
   - 支持失败自动拉起与 provider 回退 (_activate_configured_tts_fallback)
   - _enqueue_tts_text_chunk + _reset_tts_stream_normalizer 文本按句规整
   - tts_response_handler 消费音频帧并 send_speech()/send_audio_done()

4. 语音克隆 (workers/gptsovits.py):
   - GPT-SoVITS v3 WebSocket 会话式 API: init_msg={"cmd":"init","voice_id"}
   - voice_id 支持内联参数: "my_voice|{\"speed\":1.2,\"text_lang\":\"all_zh\"}"
   - get_custom_tts_voices() 拉取自定义音色, templates/voice_clone.html 克隆页

==========================================================
二、实时语音对话 Realtime (main_logic/omni_realtime_client/)
==========================================================
- OmniRealtimeClient(_ToolingMixin,_AudioMixin,_TransportMixin,
  _ResponseMixin,_GeminiMixin): 同时支持 OpenAI Realtime 与 Gemini 协议
- TurnDetectionMode 轮次检测 / RealtimeResponseArbiter 多路响应仲裁
- _audio.py: _resample_uplink() 16kHz PCM16 -> provider采样率
  (OpenAI Realtime 需24kHz, soxr FIR 尾延迟21ms)
  * 关键细节: input_audio_buffer.clear/commit 边界丢弃残留样本(不flush),
    避免上一轮尾音拼到下一轮开头
- 前端: static/audio-processor.js(降采样/VAD) + ogg-opus-decoder-wrapper.js

==========================================================
三、虚拟形象 (static/live2d/)
==========================================================
1. 口型同步 (audio-loader.js -> live2d-model.js):
   - AudioManager: ctx.createAnalyser() -> startLipSync(modelId, analyser)
   - 每帧算 RMS: mouthOpen = Math.min(1, rms*8) -> ParamMouthOpenY
   - 文件结束 stopLipSync() 复位 0
   - LIPSYNC_PARAMS = ['ParamMouthOpenY','ParamMouthForm','ParamMouthOpen',
     'ParamA','ParamI','ParamU','ParamE','ParamO']
   - LIPSYNC_OVERRIDE_THRESHOLD = 0.001: lipsync期间强制覆盖motion嘴部关键帧
   - setMouth(value): 0~1钳制+缓存参数索引(避免每帧字符串查找)

2. 表情/动作管理 (live2d-emotion.js):
   - playExpression: 先试原生 model.expression(), 失败回退
     _installManualExpressionOverride() 每帧beforeModelUpdate中lerp+300ms淡入
   - playMotion: 按 EmotionMapping.motions 随机选 .motion3.json,
     播放前 resetTransientMotionAndState({preserveExpression:true})
   - 常驻表情: applyPersistentExpressionsNative() 动作结束后重放
   - 差分淡出 smoothResetToInitialState(duration=800):
     第1帧快照表情参数值valuesA -> 停expression但不停idle motion/呼吸/
     鼠标追踪 -> 第2帧算delta -> 每帧加性叠加 delta*(1-easedProgress)
     衰减到0, 全程视觉零跳变 (全项目最精巧的动画工程)
   - 参数基线三快照: initialParameters/motionBaselineParameters/
     appearanceBaselineParameters + _findRecordedParameterBaseline 分层回退
   - _activeMotionParamIds 追踪 motion 实际改写的参数集, 恢复时只复位那部分

3. 帧率调控 (live2d-core.js):
   - 静止降 LIVE2D_IDLE_FPS=30, 交互后维持满帧900ms再衰减
   - LIVE2D_IDLE_FPS_GOVERNOR_INTERVAL_MS=300 节流采样

4. 形态与桌面集成:
   - templates/viewer.html 按序加载 live2d-core/emotion/model/
     interaction/ui-buttons/init 六个模块
   - Electron桌宠运行时标记: __LANLAN_IS_ELECTRON_PET__ /
     __NEKO_DESKTOP_RUNTIME__ / __nekoNiriPetPhysicalCrop(裁剪显示)
   - templates/subtitle.html(字幕) / toast.html(通知) / return-ball.html

==========================================================
四、主动陪伴 (main_logic/activity/ + topic/ + proactive_chat/)
==========================================================
1. 活动状态机 (activity/state_machine.py): 纯规则引擎零LLM
   - ActivityStateMachine 输入系统快照+窗口观测+语音事件+对话时间戳
     数值信号靠30s滚动平均
   - 状态: away/stale_returning/gaming/focused_work/casual_browsing/
     focused_video/chatting/voice_engaged/idle/transitioning/private
     * private命中隐私黑名单: 不分类不缓存跳过LLM富化, 硬钉为closed
   - 倾向 Propensity: closed/restricted_screen_only/open/greeting_window
     (多状态折叠到同一倾向, prompt层逻辑统一)
   - 语调 ActivityTone 七种: terse/hushed/mellow/playful/witty/warm/concise
     * witty带内容质量闸[PASS]机制(宁沉默不硬凑), 与概率闸独立通道
   - 采集: UserActivityTracker + 进程级SystemSignalCollector
     hooks: on_user_message/on_ai_message/on_voice_mode/on_voice_rms/
     on_screenshot
   - 20s轮询 activity_guess 后台循环(状态签名没变就短路省LLM)
     + ActivityGuessGate 自适应退避

2. 主动话题信号 (topic/signals.py):
   - TopicSignalStore 全局慢信号: 每轮500token上限/60轮/保留12小时
     _FILLER_TEXTS 填充词过滤
   - 候选成熟60s, 触发间隔4h, 每日上限2次
   - 被用户忽视只扣1/3配额 (_UNANSWERED_TOPIC_WEIGHT=1/3)

3. 主动对话服务 (proactive_chat/service.py):
   - 两阶段: Phase1 一次合并LLM调用做网络源筛选+音乐/梗关键词识别
     Phase2 人格化对话生成
   - decisions.py 决策链: entry_guard -> game_route_guard -> busy_guard
     -> closed_activity_gate -> probabilistic_activity_gate(概率闸)
     -> _select_source_modes -> _select_weighted_sources
   - 来源权重指数衰减: _SOURCE_WEIGHT_DECAY_LAMBDA=0.002, K=0.30,
     FLOOR=0.20, 窗口1小时
   - 去重: 近1h聊天记录+文本相似度>=0.90硬拒绝; 落盘 proactive_chat_totals.json
   - 其他: break_reminders休息提醒/mini_game_invite小游戏/music_recommendation

==========================================================
五、五维记忆系统 (memory/)
==========================================================
1. facts.py FactStore (Tier1 事实):
   - LLM从对话抽取原子事实; SHA-256哈希+FTS5语义检索双路去重
   - JSON持久化, 7天后归档(_ARCHIVE_AGE_DAYS=7, 归档冷却24h)
   - 抽事实与信号检测分模型tier; 事实带importance(safe_importance防御)
2. reflection/manager.py ReflectionEngine (Tier2 反思):
   - 事实综合成反思, pending->confirmed生命周期
   - Mixin组装: Synthesis/Refinement/EvidenceFlow/Surfacing/Promotion
3. persona/manager.py PersonaManager (Tier3 人格):
   - 按角色维护persona文件, 动态实体区块: master(主人)/neko(自己)/
     relationship(关系)
   - Mixin: Facts/Corrections/Refinement/ExternalFusion/Mentions/Rendering

==========================================================
六、情绪引擎 (两条独立通道)
==========================================================
1. 外显情绪->形象表情 (config/prompts/prompts_emotion.py):
   - OUTWARD_EMOTION_ANALYSIS_PROMPT: 五分类 happy/sad/angry/surprised/
     neutral, 输出 {"emotion":..., "confidence":0~1}, 6语种模板
   - 规则: 撒娇掩盖的委屈判sad; 口癖不算情绪证据; surprised不因感叹号误判
2. 内隐情绪追踪 (activity/master_emotion.py):
   - MasterEmotion 追踪用户情绪: valence<->arousal 二维
   - FocusScorer: distress = 高唤醒x负效价(用户烦躁时AI收敛打扰)
   - 与驱动avatar表情的OUTWARD管线是两条独立通道

==========================================================
七、对本项目最有借鉴价值的 8 点
==========================================================
1. AudioDoneEmitter哨兵协议: 音频流结束做显式消息, 被中断时不发,
   口型/进度逻辑绝对可靠
2. RMS*8口型驱动+阈值覆盖: mouthOpen=min(1,rms*8), LIPSYNC_OVERRIDE_
   THRESHOLD=0.001 让lipsync抢过motion关键帧
3. 差分淡出(smoothResetToInitialState): 表情消失先算delta再加性衰减,
   基础动作不中断, 动画无缝
4. 参数基线三快照+精确追踪: 只复位motion动过的参数, 不杀常驻状态
5. 两阶段主动对话: Phase1筛选源(成本摊薄), Phase2人格生成(预算留给创作)
6. propensity抽象+隐私硬关闭: 11状态折叠4倾向; private链路不采集不LLM
7. 来源指数衰减+半衰期跳过概率: 防复读纯O(1)规则不用LLM
8. 双通道情绪: 外显(表情)与内隐(用户情绪->收敛打扰)分离独立调优

==========================================================
附加: 项目目录结构速览
==========================================================
brain/(Agent: computer_use/browser_use/openclaw/task_executor/cua)
config/(api_providers.json + prompts/ 角色/系统提示词)
main_logic/(core.py/omni_realtime_client.py/omni_offline_client.py/
  activity/ topic/ tts_client/)
main_routers/(26个路由)  memory/(facts/reflection/persona)
frontend/(react-neko-chat + plugin-manager)  plugin/(sdk+server)
app/(main_server/agent_server/memory_server.py/monitor.py)
启动: uv run python app/memory_server.py; uv run python -m app.main_server
访问 http://localhost:48911 配置API Key

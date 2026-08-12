========================================================================
NachoBot 研究报告（学习笔记）
仓库: https://github.com/Big-Sh0t114/NachoBot  (GPL-3.0, 191 stars)
基于MaiBot核心修改的AI虚拟生命: B站直播/Discord/QQ 多平台
========================================================================

==========================================================
〇、总体架构 (核心+多适配器, 4个独立部署组件)
==========================================================
互联总线: ncnk_message (自研WebSocket消息总线)
| 组件 | 职责 | 关键路径 |
|------|------|----------|
| NachoBot | MaiBot 0.10.3核心: 聊天/LLM/插件/记忆/沙盒 | NachoBot/src/ |
| Multimodal-Adapter | TTS(GPT-SoVITS/Vox)+情感分类+VLM/ASR | NachoBot-Multimodal-Adapter/ |
| Bilibili-Adapter | B站直播/评论/私聊+音频播放+远程驱动Live2D | NachoBot-Bilibili-Adapter/bili_src/ |
| Live2D-Adapter | 独立渲染进程: pygame+OpenGL窗口 | NachoBot-Live2D-Adapter/live2d_adapter/ |

消息流: 平台 -> NachoBot(LLM决策) -> ncnk_message -> Multimodal(TTS)
      -> ncnk_message -> 平台Adapter(播放/发弹幕+远程命令) -> Live2D进程
消息: MessageBase + Seg(段类型: text/voice/voice_stream/tts_text/
      command/image)

==========================================================
一、TTS 完整链路 (从LLM文本到扬声器)
==========================================================
1. 触发层: LLM自主决定要不要说话
   - NachoBot/src/plugins/built_in/tts_plugin/plugin.py
   - TTSAction(BaseAction): activation_type=LLM_JUDGE (LLM推理中按
     action_require场景自行激活), parallel_action=False
   - 60秒限频 MIN_TTS_INTERVAL=60
   - 语言偏好记忆 _language_preferences(默认ja), #lang_switch命令切换
   - 文本清洗 _process_text_for_tts: 剔除emoji/压缩重复标点/句末补句号
   - 语种不符用replyer模型改写, 失败回退FALLBACK_ZH/JA短句列表
   - 发送: send_custom(message_type="tts_text", content={"text","lang"})

2. 合成层 TTSPipeline (Multimodal-Adapter/main.py):
   - import_module() 动态导入 nachobot_multimodal.tts.backends.<GPT_Sovits|Vox>
   - 流式 stream_mode=True: tts_stream() 每4096字节chunk -> voice_stream逐片下发
   - 非流式: 按group_id缓冲队列 text_buffer_dict/buffer_task_dict
     (每群/每用户 asyncio.Queue + 后台任务) 防群消息乱序
   - 可选后处理: simulate_telephone_voice(电话音效)

3. 合成后端 GPT-SoVITS 封装 (src/tts/backends/GPT_Sovits/tts_model.py):
   - 角色预设: configs/gpt-sovits.toml [pipeline] (default_preset/
     platform_presets); load_preset() 一次设置 ref_audio_path+prompt_text+
     切换gpt_weights/sovits_weights(HTTP /set_gpt_weights)
   - build_parameters(): text_lang/prompt_lang, top_k=5, top_p=1.0,
     temperature, text_split_method=cut5, batch, streaming_mode,
     media_type=wav, repetition_penalty=1.35, sample_steps=32
   - tts()非流式: GET /tts, aiohttp, 60s超时
   - tts_stream(): requests stream=True, (3.05,None)超时, iter_content(4096)
   - 抽象基类 src/tts/base.py: BaseTTSModel 只定义 tts() 与 tts_stream()
     (换引擎成本极低——接口设计典范)

4. 句级切分 (src/utils/text_splitter.py):
   - split_text_for_streaming(text, min_segment_length=10):
     cut0整段 / cut1句号类 / cut2+逗号顿号 / cut3+分号冒号省略号 /
     cut4纯字符数(max_split_length默认80) / cut5先标点再对超长段二次切(默认)
   - 标点保留在前段末尾; _merge_short_segments: <10字的短句并入前段防碎片

5. 情感->音色预设 (src/utils/emotion_classifier.py):
   - EmotionClassifier: zero-shot NLI (MoritzLaurer/mDeBERTa-v3-base-xnli-
     multilingual-nli-2mil7), 中文假设模板"这段文字表达的情感是{}"
   - FP16半精度(CPU自动回退FP32), 惰性加载
   - _resolve_emotion_preset(text): 分类 -> confidence_threshold不足回退
     default_emotion -> tag_preset_map映射角色预设, 每次合成前切换
   - 分类器只在TTS服务端跑; B站Adapter通过GET /api/emotion_preset?text= 远程查

6. 播放层 (Bilibili-Adapter bili_src/audio/):
   - tts_manager.py:
     * 双语标签智能缓冲 buffer_tts_reply(): LLM回复体含<JP>...</JP>/<ZH>...
       标签(日文播报+中文显示), 等0.5s合并, 检查标签配对平衡, 超时修复
     * process_buffered_live_reply(): split_text_for_streaming逐句tts ->
       audio_player.play()依次入队; 首段音频就绪即触发 on_start_replying()
       + execute_live2d_action(emotion,action) + interrupt_idle()
       (开口就动的零等待)
     * update_subtitle() 写subtitles.txt(OBS字幕)
     * 空闲语音 idle_tts_loop: 随机间隔(10s~max)说预设idle_tts_texts
     * 命令: #tts_on/#tts_off/#lang_switch/#idle_on/#idle_off(带权限校验)
   - audio_player.py:
     * AudioPlayer 单播放循环 + deque队列((audio_data, is_idle)标记)
     * idle音频可被正常回复打断: interrupt_idle清队列+stop_event.set()
     * 优先走 remote_playback_callback(让Live2D渲染进程播放, 使OBS把声音
       关联到桌宠窗口), 失败回退 winsound

==========================================================
二、Live2D 实现 (重点)
==========================================================
1. 协议层 (live2d_adapter/protocol.py):
   - PROTOCOL_VERSION="1.0"; 消息类型 avatar.command / avatar.interaction
   - 下行 AvatarEvent: STATE/SPEAKING/EMOTION/ACTION/MOTION/
     RANDOM_MOTION/GAZE/PARAM_TWEEN/PLAY_AUDIO/STOP_AUDIO/SHUTDOWN/PING
   - 上行 AvatarInteraction: READY/CLICK/POKE/PONG/ERROR
   - 纪律: 平台消息对象绝不跨越此边界, 外部只与AvatarCommand交互

2. 运行时 (runtime.py):
   - AvatarRuntime: command_queue=queue.Queue() + render_thread(daemon)
     + asyncio主循环; dispatch() 协议校验与翻译
     (SPEAKING->"speaking", ACTION->action_id经config.resolve_action()
     映射到motion组, PLAY_AUDIO->base64解码wav校验+4MiB上限)
   - 上行: render线程用 asyncio.run_coroutine_threadsafe 回投事件循环
   - POKE 带 poke_cooldown_seconds 冷却

3. 渲染器 (renderer.py, 999行):
   - 技术栈: pygame + OpenGL(GL_MULTISAMPLEBUFFERS=4抗锯齿)
     + live2d.v3 (live2d-python SDK, 导入前清sys.modules缓存修复DLL问题)
   - 坑: 加载模型前 os.chdir(model_dir)(SDK缓存CWD), 加载后恢复;
     ./前缀解决空路径; DPI awareness防模糊
   - 透明桌宠窗: NOFRAME|RESIZABLE + WS_EX_LAYERED + LWA_COLORKEY
     (黑色键控) -> 透明 + HWND_TOPMOST置顶
   - 口型: SPEAKING事件->is_speaking->每帧mouth_phase+=0.12,
     三正弦叠加 0.4*sin(2.5φ)+0.3*sin(1.8φ)+0.3*sin(3.3φ) 归一化[0,1]
     -> SetParameterValue("ParamMouthOpenY", value, 1.0)
     停止时平滑归零
   - 参数补间 PARAM_TWEEN: active_tweens列表{param,start,end,time,dur},
     每帧ease-out quad插值; 交互后1秒安全冷却(防鼠标Drag竞争);
     写入前用available_param_ids(GetParamIds())校验
   - 凝视 GAZE/AUTO_GAZE: target_x/y -> 每帧lerp(速度0.01) ->
     映射屏幕坐标 -> model.Drag()
   - 状态->视线表: start_viewing->(-0.5,-0.2)看聊天区/
     start_thinking->(0.3,0.5)看气泡/start_replying->(0,0)直视/
     finish_reply->(0,0)回正 (对话状态机驱动眼神!)
   - 表情: emotion命令({joy:5,anger:1}强度字典取最大值>=3才生效)
     -> expr_map映射(joy->f01) -> SetExpression()
   - 动作: motion=StartMotion(group,no,3) priority3强制打断
   - 音频: pygame.mixer.Sound(file=io.BytesIO(wav_bytes))
     (让OBS把声音关联到渲染窗口的关键)

4. 远程驱动 (Bilibili-Adapter bili_src/live2d/):
   - remote_controller.py: WebSocket客户端连 ws://127.0.0.1:8766 + token鉴权,
     断线自动重连, _send_queue maxsize 256, 8MiB消息上限
   - live2d_manager.py:
     * extract_json_emotion_from_text(text): LLM回复文本内嵌JSON,
       截取第一个{到最后一个}解析出(reply,emotion,action)
     * execute_extracted_live2d_action: 中文动作经_ACTION_TO_CANONICAL_ID
       映射(待机/放松->IDLE, 眨眼/卖萌/Wink->WINK, 歪头/思考->TILT_HEAD,
       害羞->LOOK_AWAY...) 后 send_live2d_event
   - 时序: 回复到达 -> TTS启用的房间走缓冲队列 -> 首段音频就绪
     on_start_replying()(发STATE/SPEAKING) -> 播放中口型随SPEAKING=true
     摆动 -> on_reply_finished() 复位

==========================================================
三、多模态本地部署
==========================================================
- TTS服务(Multimodal-Adapter端口9872): HF_HOME=models/hf_cache +
  HF_ENDPOINT=https://hf-mirror.com; /api/tts /api/health /api/emotion_preset
- 感知服务(src/api_server.py): FastAPI Perception API
  * POST /v1/chat/completions: Florence-2做图像描述(OpenAI兼容格式)
  * POST /v1/audio/transcriptions: FunASR
  * startup事件 asyncio.to_thread 预加载模型, DISABLE_VLM_ASR=1跳过
- 三进程独立只通过ncnk_message/HTTP/WebSocket通信——坏一个不影响其他

==========================================================
四、记忆/誓约/沙盒
==========================================================
1. 誓约系统 (src/chat/keyword_cache/promise_cache_manager.py):
   - PromiseCacheManager(全局单例): 配置promise_cache(enable/keywords/
     context_size/post_context_size/max_cache_per_keyword/cache_dir)
   - 仅私聊(群聊跳过)
   - 捕获: 命中关键词 -> 取关键词前context_size条+当前消息 落盘raw/目录
     (按chat_id/关键词/日期_会话_时间戳分文件)
   - 摘要: 消息停止180s(_idle_wait_then_scan) -> LLM提炼3-6条要点
     ("只保留事实与约定, 去掉说话人和时间戳") -> 写processed/
   - 注入: collect_snippets_for_messages() 构建回复上下文时扫描关键词,
     返回 "[关键词:xxx] 摘要于 2026-07-31 ..."
   - 成本低: 只在关键词命中时动用LLM

2. 记忆图谱海马体 (src/chat/memory_system/Hippocampus.py):
   - MemoryGraph (networkx图): 节点=主题(memory_items+weight), 边=关联(strength)
   - 沉淀: MemoryAccumulator + ParahippocampalGyrus.memory_compress
     (每日02:00定时, 取近48h消息) -> LLM提取主题(<>尖括号解析) ->
     每主题并行摘要 -> jieba分词词集余弦相似度>=0.7视为相似 ->
     add_memory_with_similar 建节点边强度int(similarity*10)
   - 检索: get_memory_from_topic 关键词BFS扩散激活
     new_activation = current - 1/strength(强度越大衰减越少), 深度上限3;
     累计激活值按平方加权概率随机挑选(人类回忆随机性) -> LLM二次筛选memory_ids
   - 遗忘: operation_forget_topic 随机采样0.5%节点/边, 超时未修改强度-1,
     归零移除
   - 关系/印象记忆 (plugins/built_in/relation/): BuildRelationAction
     (LLM_JUDGE激活) 印象写入分类记忆点, LLM判断"新增/加深/整合"三选一,
     整合时memory_weight+1.0; GetPersonInfoTool随时查询
   - 另有 src/memory_system/: 中期记忆(embedding检索mid_term_memory*) +
     检索工具集(query_chat_history/query_person_info/query_words...)

3. 伪Agent沙盒 (src/chat/sandbox/):
   - sandbox_manager.py: Sandbox(per chat_id, 目录data/sandbox/<chat_id>);
     save_file用Path(filename).name清洗+重名_1后缀;
     FileSummaryEntry: LLM生成文件摘要, remaining_rounds=3轮注入后自动过期
     (防prompt膨胀); recent_reads最多3个文件
   - sandbox_tools.py: ReadFileTool(name=read_file)权限校验双层:
     admin(global_config.advanced.admins)或sandbox_whitelist,
     且必须从context取真实发送者(防群聊冒充)
   - 注入 (chat/injection/injection_manager.py): 关键词/正则匹配主题 ->
     组装[注入:主题]提示块, remaining_rounds持续数轮/cooldown_turns冷却;
     mus_library动态随机采样歌单注入

4. 回复器流水线 (chat/replyer/ + message_receive/):
   - bot.py message_process -> ChatManager.get_or_create_stream
     (stream_id=md5(platform_groupId)或md5(platform_userId_private),
     并发安全创建任务去重) -> ReplyerManager.get_replyer 按会话缓存
   - private_generator.py: _time_and_run_task 并行构建prompt块
     (memory_block图谱激活记忆 + mid_term_memory_block + 沙盒文件摘要)
     -> LLM生成 -> action系统(LLM_JUDGE类) -> send_api下发

==========================================================
五、对本项目最有借鉴价值的 9 点
==========================================================
1. 文本内嵌JSON元数据+截取解析(零成本双通道):
   extract_json_emotion_from_text: LLM输出"回复正文{emotion,action}",
   只截首尾大括号解析, 正文照常TTS/显示。不用为表情单独调一次LLM,
   失败安全。口型联动的SPEAKING命令也由同一段文本驱动
2. 渲染线程+命令队列+协议边界: 渲染独立线程, 主线程只put_nowait;
   协议带版本号/事件枚举/PING/PONG; PLAY_AUDIO base64+4MiB上限。
   对应PyQt: 主线程别碰渲染/音频, 用QThread+queue; 音频播放放渲染侧
   能让OBS把声音关联到窗口
3. 口型=多正弦叠加+参数补间+交互冷却: 三正弦(0.4/0.3/0.3 x 2.5/1.8/3.3)
   合成口型值写ParamMouthOpenY; active_tweens ease-out quad缓动;
   鼠标交互后1s内跳过参数写入防竞争
4. 逐句切分+首段即触发+队列播放(低延迟流式): cut0~5切句+短句合并;
   首段就绪立刻触发开口动画并打断空闲语音; (data,is_idle)双优先级队列
5. 情感分类->音色/预设映射带置信度回退: zero-shot分类->低置信度回退
   默认->tag_preset_map切音色预设。Edge-TTS多音色可做同样情绪映射
6. 誓约缓存(关键词触发式长期约定记忆): 关键词命中->捕获前后N条->
   空闲180s LLM压成3-6条要点->下次命中注入。纯JSON落盘无向量库,
   只在命中时花token
7. 记忆图谱检索=BFS激活扩散+平方概率采样+LLM二次筛选:
   networkx实现, SQLite存节点/边即可复刻; 每日批量LLM沉淀+遗忘衰减
8. 60s限频+LLM_JUDGE触发+语言偏好持久化: LLM自己决定何时用语音,
   防刷屏; 桌面场景扩展为"忙碌检测+语音开关+语种偏好"
9. 回声过滤(防自嗨): is_self_danmu记录自己发的弹幕(ID+2.5s/6s文本窗口),
   不回复自己的话。桌面语音交互做VAD时同理: 扬声器放出的内容不得触发
   麦克风回调

==========================================================
六、一句话总结
==========================================================
核心不是某个算法而是纪律: 进程隔离+版本化消息协议+文本内嵌元数据
单通道复用+队列化/缓冲化的一切+LLM只在关键节点介入(激活/摘要/分类)。

================================================================================
YHLZ 2.0 改进蓝图 v1.0
================================================================================
版本: 1.0 | 日期: 2026-07-31
依据: 项目结构白皮书 + NEKO/NachoBot 学习笔记 + 本项目基线
原则: 不做大重构，按"缺口→方案→落地路径"逐项补齐；
      优先补齐 说话(TTS) 与 虚拟形象(桌宠/Live2D) 两条主线。

--------------------------------------------------------------------------------
〇、差距总览 (本项目 vs 成熟项目)
--------------------------------------------------------------------------------
| 维度          | YHLZ 2.0 现状            | N.E.K.O               | NachoBot            | 差距等级 |
|--------------|--------------------------|-----------------------|--------------------|----------|
| TTS引擎抽象   | 单引擎Edge-TTS          | 三类Provider+回退     | BaseTTSModel抽象+双后端 | ★★★ |
| 说话延迟     | 累积2秒才播             | 碎片即推(ws_bistream) | 首段就绪即触发      | ★★★ |
| 流式收尾     | 隐式推断                | __audio_done__哨兵    | voice_stream逐片    | ★★ |
| 口型同步     | 0.1s chunk RMS          | RMS*8+阈值覆盖+参数保护 | 三正弦叠加+补间    | ★★★ |
| 表情系统     | 手动set_emotion         | 差分淡出+基线三快照   | 文本内嵌JSON零成本  | ★★★ |
| 主动陪伴     | screen_monitor定时截图  | 活动状态机+话题源权重 | idle_tts+限频       | ★★★ |
| 记忆         | 记忆库+誓约+关联        | 五维(事实/反思/人格)  | 图谱BFS+誓约缓存     | ★★ |
| 情绪引擎     | 无                      | 双通道(外显+内隐)     | 情感→音色预设       | ★★★ |
| 协议边界     | HTTP/WS直连无版本       | 版本化+哨兵           | 协议v1.0+心跳+4MiB  | ★★ |
| 多模态感知   | vision_engine           | 屏幕理解+活动猜测     | Florence-2+FunASR   | ★★ |

优先级: P0=说话链路(5项) P1=虚拟形象(6项) P2=陪伴与记忆(4项) P3=架构(3项)

================================================================================
一、说话链路改进 (P0, 5项) —— 对标 NachoBot TTS 链路
================================================================================
■ 1.1 TTS 引擎抽象层 ★★★
  现状: tts_engine.py 直接封装 Edge-TTS
  蓝图:
  ```
  backend/tts/base.py        # BaseTTSEngine: synthesize()/stream_synthesize()
  backend/tts/edge.py        # EdgeTTSEngine(现tts_engine改造)
  backend/tts/gptsovits.py   # GPT-SoVITS引擎(可选, HTTP/WS协议复用NachoBot参数)
  backend/tts/manager.py     # TTSManager: 引擎注册+故障回退+按配置切换
  ```
  - 接口只定义 synthesize()/stream_synthesize() 两个抽象方法(NachoBot BaseTTSModel范式)
  - 引擎失败自动回退(_activate_configured_tts_fallback)
  - config.tts_engine 支持 edge-tts / gptsovits / auto
  收益: 换引擎成本从"改代码"降为"改配置"

■ 1.2 说话延迟优化: 首段就绪即开口 ★★★
  现状: _audio_player_loop 累积 target_chunk_size=2秒 才 sd.play()
  蓝图:
  - 播放线程改为"最小0.5秒+满2秒"双阈值(NachoBot min_play_size范式)
    → 首段音频到位立即开播, 累计满2秒再合并
  - TTS生产者: 现条件"≥12字符或≥6字符+标点"下调为
    "≥8字符或≥4字符+标点"(NEKO SentenceBuffer范式)
  - 增加 TTS_STREAM_FIRST_CHUNK_MS 配置(目标: 首字出声<800ms)
  收益: 首字延迟从~2s降到~0.8s, 对话"活"起来

■ 1.3 流式收尾哨兵 __audio_done__ ★★
  现状: 音频结束靠播放完隐式复位口型
  蓝图(对齐NEKO TTS_AUDIO_DONE_SENTINEL):
  - tts_engine.stream_synthesize 每轮结束 yield ('done', None) 标记
  - audio_buffer 增加 is_stream_done 状态; 播放线程消费 done 后再复位口型
  - 被 interrupt 打断的流不发送 done → 口型保持张合, 前端不误复位
  收益: 口型/播放进度逻辑绝对可靠

■ 1.4 情绪→音色映射 (Edge-TTS多音色利用) ★★
  现状: 固定 zh-CN-XiaoxiaoNeural
  蓝图:
  - text_postprocessor 或独立 emotion_classifier:
    规则+轻量分类(先正则关键词, 可选zero-shot模型) → 情绪五分类
  - 映射表(参考NachoBot tag_preset_map):
    happy→XiaoyiNeural(活泼) / calm→XiaoxiaoNeural(温柔) /
    sad→XiaomoNeural(低沉) / angry→YunjianNeural(稳重) /
    default→XiaoxiaoNeural
  - 低置信度回退默认(confidence_threshold)
  - /synthesize 接口增加 emotion 参数
  收益: 声音随内容变化, 无需新模型

■ 1.5 说话防自嗨 (回声过滤) ★★
  现状: 无 — 扬声器声音可能触发麦克风ASR
  蓝图(对齐NachoBot is_self_danmu):
  - audio_buffer 记录本机播放时间窗(2.5s/6s双窗口)
  - conversation_manager 决策前检查: 若输入落在自播窗口→丢弃/标记
  - 与 echo_cancellation 双保险
  收益: 大幅减少"AI回应自己"的幻听循环

================================================================================
二、虚拟形象改进 (P1, 6项) —— 对标 N.E.K.O Live2D 工程
================================================================================
■ 2.1 口型同步升级: RMS×8 + 参数保护 ★★★
  现状: 每0.1s chunk 算一次RMS→ParamMouthOpen(无放大无保护)
  蓝图(对齐NEKO audio-loader.js + live2d-model.js):
  - mouthOpen = min(1.0, rms × 8)   (能量放大映射)
  - 每帧更新(帧循环内), 不再等0.1s chunk
  - LIPSYNC_PARAMS 保护集: ['ParamMouthOpen','ParamMouthOpenY',
    'ParamMouthForm','ParamA','ParamI','ParamU','ParamE','ParamO']
  - LIPSYNC_OVERRIDE_THRESHOLD=0.001: 说话期间强制覆盖motion嘴部帧
  - 桌宠端: desktop_avatar_py.py 增加 AudioAnalyser(QAudioProbe/RMS分析)
  收益: 口型"永远跟着人声走", 不被待机动作覆盖

■ 2.2 表情/动作系统: 基线三快照 + 差分淡出 ★★★
  现状: _set_emotion 直接换表情
  蓝图(对齐NEKO live2d-emotion.js):
  - 建立三套参数快照:
    initialParameters(初始) / motionBaselineParameters(动作前) /
    appearanceBaselineParameters(外观)
  - _activeMotionParamIds: 记录motion实际改写的参数, 恢复只复位那部分
  - 表情消失用"差分淡出"(smoothResetToInitialState):
    快照→算delta→每帧 delta×(1-ease(t)) 衰减, 待机呼吸不中断
  - 常驻表情(咬唇/微笑): applyPersistentExpressions 动作后重放
  - 帧率调控: 静止30fps / 交互后满帧900ms再衰减(NEKO governor)
  收益: 表情切换动画无缝, 质感提升一个量级

■ 2.3 文本内嵌JSON元数据: 零成本表情驱动 ★★★ (NachoBot核心套路)
  现状: 表情需额外接口手动触发
  蓝图(对齐 extract_json_emotion_from_text):
  - LLM system prompt 要求回复末尾附 {"emotion":"happy","action":"wink"}
  - 后端解析: 截取首个{到末尾} → (reply_text, emotion, action)
    解析失败→当纯文本(失败安全)
  - reply_text 走TTS; emotion/action 走 sync_manager → 桌宠
  - 中文动作映射表(对齐 _ACTION_TO_CANONICAL_ID):
    待机/放松→IDLE, 眨眼/卖萌→WINK, 歪头/思考→TILT_HEAD,
    害羞→LOOK_AWAY, 生气→ANGRY, 开心→JOY, 惊讶→SURPRISED
  收益: 表情与说话零延迟联动, 不额外消耗LLM调用

■ 2.4 协议边界: 版本化消息 + 心跳 + 尺寸上限 ★★
  现状: 桌宠与后端HTTP/WS直连, 无协议约束
  蓝图(对齐NachoBot protocol.py):
  - 定义 avatar_command/avatar_interaction 消息类型
  - 事件枚举: STATE/SPEAKING/EMOTION/ACTION/GAZE/PARAM_TWEEN/
    PLAY_AUDIO/STOP_AUDIO/PING/PONG
  - 消息带 PROTOCOL_VERSION + 4MiB音频上限 + PING/PONG健康检查
  - 播放音频放在"形象侧"(桌宠进程) → 便于OBS关联窗口声音
  收益: 通信可靠, 支持未来多客户端

■ 2.5 对话状态机驱动眼神/视线 ★★ (NEKO + NachoBot)
  现状: 无视线概念
  蓝图:
  - 状态: start_viewing(看聊天区) / start_thinking(看气泡) /
    start_replying(直视用户) / finish_reply(回正)
  - 参数补间 active_tweens: {param,start,end,start_time,duration}
    ease-out quad插值; 交互后1s安全冷却(防鼠标Drag竞争)
  - GAZE: 鼠标位置→Live2D Drag()跟随(lerp 0.01)
  收益: 形象"活"了——思考时眼神飘走, 说话时看着你

■ 2.6 VTS联动增强 ★★
  现状: vts_client.py 已有认证/表情/触发器
  蓝图:
  - VTS口型参数映射表: SPEAKING→MouthOpen, RMS→MouthOpen(数值驱动)
  - 复用2.3的JSON元数据: emotion→VTSExpression
  - 增加 VTS 参数平滑(补间)与交互冷却
  收益: 桌宠与VTS形态共用同一套表情协议

================================================================================
三、主动陪伴与记忆 (P2, 4项)
================================================================================
■ 3.1 活动状态机 (纯规则, 零LLM) ★★★
  蓝图(对齐NEKO activity/state_machine.py):
  - ActivityStateMachine: 输入(系统快照+窗口标题+语音事件+时间)
    → 输出状态: away/focused_work/gaming/casual_browsing/idle/chatting
  - 折叠为4倾向(propensity): closed/restricted_screen_only/open/greeting
  - 隐私黑名单: 命中敏感窗口→不采集不分析
  - 30s滚动平均平滑数值信号
  落地: backend/activity.py 新模块; vision_engine 提供窗口标题
  收益: 知道用户在干什么, 是主动陪伴的前提

■ 3.2 主动话题源: 权重衰减 + 防复读 ★★★
  蓝图(对齐NEKO proactive_chat):
  - 话题源: 屏幕内容/时间问候/热搜(可选B站client)/记忆提醒
  - 每个源权重指数衰减(λ=0.002, FLOOR=0.20), 1小时窗口
  - 防复读: 近1h消息+相似度≥0.90硬拒绝; 半衰期跳过概率
  - 触发节流: 最小间隔4h, 每日上限2次, 被忽略只扣1/3配额
  - 两阶段: Phase1轻量筛选源 → Phase2人格化生成(成本摊薄)
  落地: backend/proactive.py 新模块 + plugins/screen_monitor 改造
  收益: "她会主动找你聊天"的核心能力

■ 3.3 事实记忆抽取 + 遗忘衰减 ★★
  蓝图(对齐NEKO facts.py + NachoBot Hippocampus):
  - extract_from_dialogue 升级: 抽"原子事实"(谁/何时/何事)
    带importance, SHA-256+语义双路去重, 7天归档
  - 遗忘: 定期prune, 长时间未访问的记忆权重衰减, 归零删除
  - 摘要合并: 对话空闲后LLM压成3-6条要点写入(关键词命中才调用)
  落地: memory.py 增加 extract_facts/prune_by_weight
  收益: 越聊越懂且不膨胀

■ 3.4 情绪引擎 (双通道) ★★
  蓝图(对齐NEKO prompts_emotion.py + master_emotion.py):
  - 外显通道: LLM每轮输出五分类情绪(可并入2.3的JSON元数据,零额外调用)
    规则: 撒娇掩盖的委屈判sad; 口癖不算证据
  - 内隐通道: 追踪用户情绪 valence×arousal;
    distress=高唤醒×负效价 → 减少打扰(忙碌检测)
  落地: backend/emotion.py + 融入context_manager.add_emotion_record
  收益: 既有表情又有分寸

================================================================================
四、架构级改进 (P3, 3项)
================================================================================
■ 4.1 配置外置: .env 增加 TTS_ENGINE/EMOTION_ENABLED/
    PROACTIVE_ENABLED/ACTIVITY_ENABLED 开关 ★
■ 4.2 日志分级: 后端 INFO→DEBUG 由环境变量控制, 减少冗余日志 ★
■ 4.3 模块单测: 为 tts_manager/emotion/activity 补 pytest
    (现有 test_*.py 已清理, 建立 backend/tests/) ★

================================================================================
五、实施路线图
================================================================================
阶段1 (1-2天, 说话链路P0): 1.1引擎抽象 → 1.2低延迟 → 1.3哨兵 → 1.5回声过滤
阶段2 (2-3天, 形象基础P1): 2.1口型升级 → 2.2表情系统 → 2.4协议边界
阶段3 (2-3天, 形象智能P1): 2.3文本JSON → 2.5视线状态机 → 2.6 VTS联动
阶段4 (3-5天, 陪伴P2):   3.1活动状态机 → 3.2主动话题 → 3.4情绪引擎
阶段5 (2-3天, 记忆P2):   3.3事实抽取/遗忘 → 3.4内隐情绪追踪
阶段6 (1-2天, 收尾P3):   配置开关/日志/单测
合计: 约2-3周兼职工作量, 每阶段可独立上线

================================================================================
六、风险与依赖
================================================================================
- 2.2差分淡出: 依赖当前Live2D渲染是自研renderer还是WebView版,
  需确认 desktop_avatar_py.py 的 Live2D 参数写入路径
- 1.4情绪音色: Edge-TTS音色情感区分有限, 效果不达预期可降级为
  语速/语调调整(rate/pitch参数)
- 3.1活动状态机: 需要窗口标题捕获权限(win32gui)
- 2.3文本JSON: 需prompt调优, 防止LLM不输出或乱输出(失败安全兜底)
================================================================================

# YHLZ Conversation Runtime V10.1.8 热机修正版工程 Prompt

## 目标

基于当前 V10.1.7 对话规则架构、流式设计和 DEMO
流模式，对热机阶段进行修正升级。

核心目标：

将 YHLZ 从 Stable Conversation Runtime 升级为 Real-time AI Companion
Runtime。

原则：

稳定性 \> 对话体验 \> 可观察性 \> 性能优化 \> 高级能力扩展

禁止推倒现有 Streaming。

------------------------------------------------------------------------

# 一、上下文系统升级

当前问题：

MAX_HISTORY_MESSAGES=3 过短。

升级：

短期窗口： 6\~10轮原始上下文。

超过窗口：

原始消息 ↓ Conversation Compression ↓ 工作摘要 ↓ 继续对话

压缩必须保留：

-   用户目标
-   当前任务
-   已确认结论
-   未完成事项
-   关键实体

上下文优先级：

Current Conversation \> Working Summary \> Relevant Memory \> Long-term
Memory

------------------------------------------------------------------------

# 二、回声控制重新设计

删除文本重叠判断作为主要方案。

原因：

ASR文本无法可靠判断用户声音与AI声音。

调整为音频层处理：

TTS Output ↓ Browser Audio Layer ↓ AEC ↓ Noise Suppression ↓ AGC ↓
Microphone ↓ ASR

要求：

启用：

-   WebRTC Echo Cancellation
-   Noise Suppression
-   Auto Gain Control

文本检测只作为异常保护。

------------------------------------------------------------------------

# 三、Interrupt Controller升级

重新定义打断边界。

LLM取消：

只负责模型仍在生成阶段。

TTS控制：

最高优先级。

流程：

用户打断 ↓ Interrupt Controller ↓ 判断阶段

LLM生成中： 取消生成

TTS播放中： 停止播放

播放队列： 清理低优先级任务

恢复监听。

------------------------------------------------------------------------

# 四、连续输入治理

FIFO Queue 不作为最终方案。

增加：

Input Aggregator

流程：

Input Stream ↓ Classifier ↓ Merge ↓ Priority Queue ↓ Conversation
Manager

功能：

-   重复问题合并
-   无意义输入降权
-   重要问题优先
-   直播弹幕筛选

------------------------------------------------------------------------

# 五、Progressive Streaming

通过 Prompt 降低体感延迟。

复杂问题：

先输出短确认：

"我理解你的问题，我先分析核心原因。"

然后继续：

-   核心结论
-   详细解释
-   补充建议

------------------------------------------------------------------------

# 六、Streaming保持并优化

保留：

LLM Streaming → SSE → WebUI

规则：

-   首片快速发送
-   句级切分
-   短周期flush
-   避免大段等待

------------------------------------------------------------------------

# 七、并行TTS

保留：

句级预合成。

流程：

LLM Streaming ↓ Sentence Split ↓ TTS Queue ↓ Parallel Generate ↓
Priority Dispatcher ↓ Sequential Playback

优先级：

当前播放 \> 下一句 \> 未来句

打断时：

立即取消低优先级TTS。

------------------------------------------------------------------------

# 八、Conversation状态机升级

状态：

IDLE

RECEIVING

READY

PROCESSING

STREAMING

TTS_PLAYING

COMPLETED

异常：

INTERRUPTED

ERROR

RECOVERY

所有状态：

必须可记录、可恢复、可诊断。

------------------------------------------------------------------------

# 九、可观察性

记录：

Conversation：

-   conversation_id
-   turn_id
-   state

Streaming：

-   first_token
-   first_sentence
-   flush_time

TTS：

-   synth_start
-   synth_end
-   playback_start

Interrupt：

-   interrupt_time
-   stopped_layer
-   recovery_time

------------------------------------------------------------------------

# 十、WebUI状态栏

增加：

Conversation状态

Context窗口占用

Memory状态

TTS状态

Interrupt状态

Latency：

TTFT

TTS Start

Total Response Time

------------------------------------------------------------------------

# 十一、验收测试

必须测试：

1.  20轮连续交流

2.  上下文压缩

3.  AI播放期间回声测试

4.  TTS播放中打断

5.  100条连续输入筛选

6.  长回复Streaming

7.  长文本TTS连续播放

8.  长时间运行稳定性

------------------------------------------------------------------------

# 十二、最终READY标准

必须满足：

-   对话自然
-   上下文稳定
-   压缩有效
-   无明显回声
-   打断可靠
-   输入治理正常
-   Streaming流畅
-   TTS连续
-   日志完整
-   WebUI状态真实
-   长时间运行稳定

最终：

Stable Conversation Runtime

↓

Real-time AI Companion Runtime

↓

YHLZ 元亨完整能力

# YHLZ 热机时期总改进工程 Prompt

版本：V10.1.7
项目：YHLZ AI伙伴「元亨」
阶段：正式热机阶段

## 一、最高优先级

当前唯一最高目标：

> 让 YHLZ 形成一个稳定、可观察、可恢复、可持续对话的热机运行核心。

优先级：

稳定性 > 对话体验 > 可观察性 > 可维护性 > 性能优化 > 高级能力扩展

任何新功能如果降低基础对话稳定性，必须暂缓。

## 二、现有基础必须保留

当前正式 WebUI 已采用：

`/api/chat/stream → ReadableStream → SSE`

禁止为了重新设计对话系统而推倒现有 Streaming。

当前 Streaming 作为底层传输能力保留。

当前 Demo 已验证并应作为改进依据的机制：

- LLM `generate_stream`
- 句级切分
- 首片快速发送
- 后续短周期 flush
- barge-in 中断令牌
- 超时排队
- 失败哨兵
- LatencyTracker
- 非流式回退路径

## 三、当前真正需要解决的问题

重点不是重新实现 Streaming，而是补齐 Conversation Control：

1. 用户什么时候完成输入；
2. 系统什么时候开始处理；
3. 处理期间如何继续接收输入；
4. 用户打断时如何取消当前生成；
5. 新输入如何避免丢失；
6. Streaming 什么时候开始；
7. Streaming 如何分段刷新；
8. 当前回答什么时候真正结束；
9. 下一轮什么时候重新开放；
10. 所有状态如何被日志和 WebUI 观察。

## 四、目标架构

```text
WebUI
 ↓
Input Receiver
 ↓
Turn Controller
 ↓
Conversation State
 ↓
Runtime
 ↓
LLM Streaming
 ↓
Stream Controller
 ↓
SSE
 ↓
WebUI Renderer
```

Turn Controller 不替代 Streaming。

Streaming 是输出传输层。

Turn Controller 是对话生命周期控制层。

## 五、Conversation State Machine

必须实现明确状态：

```text
IDLE
 ↓
RECEIVING
 ↓
READY
 ↓
PROCESSING
 ↓
STREAMING
 ↓
COMPLETED
 ↓
IDLE
```

异常路径：

```text
PROCESSING / STREAMING
 ↓
INTERRUPTED
 ↓
QUEUED / READY
```

每个状态必须：

- 有明确进入条件
- 有明确退出条件
- 可记录
- 可恢复
- 可诊断

禁止隐式状态。

## 六、输入接收规则

建立 Input Window。

必须支持：

- 正常提交
- 连续输入
- 快速连续输入
- 当前回答期间输入
- 打断当前回答
- 排队后续输入

如果已有明确提交机制，优先保留。

对于文本聊天，明确提交优先作为 Turn Boundary，例如发送按钮 / Enter。

自动等待窗口只能作为辅助机制。

所有阈值必须配置化、可测试、可回退。

禁止凭经验硬编码最终阈值。

## 七、用户打断规则

用户在 PROCESSING / STREAMING 时产生新输入：

必须支持 Barge-in。

执行：

1. 创建新的 turn_id；
2. 取消旧生成；
3. 停止继续向前端输出旧内容；
4. 保存必要的中断状态；
5. 新输入进入 READY；
6. 重新处理。

禁止：

- 旧回答继续输出到新问题之后；
- 新输入静默丢失；
- 打断导致上下文污染。

参考 Demo 的 generation token 对比机制。

## 八、连续输入排队

如果当前任务无法立即取消：

进入 Queue。

Queue 必须：

- 有序
- 可追踪
- 不丢失
- 有上限
- 超限有明确错误

每条消息至少具有：

```text
turn_id
timestamp
state
source
content_hash
```

## 九、Streaming 输出规则

保留：

`LLM Streaming → SSE → WebUI`

禁止等待完整 Response 后一次性返回。

必须支持：

- 首片快速输出
- 持续刷新
- 完成事件
- 错误事件
- 中断事件

## 十、Stream Flush

禁止每个 token 单独刷新前端。

也禁止长时间积累后一次性输出。

采用：

短文本缓冲 + 时间窗口 + 语义分段。

优先参考 Demo：

- 首片尽快发送
- 后续短周期 flush
- 句级切分
- 避免句间明显卡顿

具体数值必须通过 Benchmark 决定。

## 十一、输出事件协议

Streaming 输出至少支持：

```text
START
TOKEN / DELTA
FLUSH
COMPLETE
INTERRUPTED
ERROR
HEARTBEAT（如需要）
```

每个事件至少包含：

```text
conversation_id
turn_id
timestamp
sequence
event_type
payload
```

前端必须保证 sequence 单调递增。

禁止旧 turn 覆盖新 turn、重复显示或乱序追加。

## 十二、Streaming 失败与回退

流式调用失败时：

1. 记录错误；
2. 标记当前 turn；
3. 执行定义好的 fallback；
4. 向前端发送明确 ERROR；
5. 释放当前 turn；
6. 恢复 IDLE 或 READY。

禁止 dispatcher 永久等待。

如果 Provider 不支持 Streaming：

允许完整生成后一次性 Response，但必须使用统一事件接口。

## 十三、上下文规则

优先级：

```text
Current Conversation
>
Working Context
>
Relevant Memory
>
Long-term Memory
```

普通短聊：

不要加载大量 Memory。

复杂项目问题：

按需加载相关 Context。

禁止每轮自动拼接全部身份、项目历史和 Memory。

## 十四、Conversation / Runtime / LLM 边界

Conversation Control：

负责：

- 接收
- Turn
- 打断
- 排队
- 输出节奏
- 状态

Runtime：

负责：

- 上下文
- 能力调用
- Memory
- Model Router
- Agent能力

LLM：

负责：

- 理解
- 推理
- 生成

不要把系统行为规则全部塞进 Prompt。

## 十五、LatencyTracker

当前已有 LatencyTracker 时必须复用，不重复创建。

至少记录：

```text
input_start
input_end
turn_start
runtime_start
llm_start
first_token
first_flush
stream_end
response_complete
turn_close
interrupt_time
queue_wait
fallback_time
```

计算：

- TTFT
- Streaming Rate
- Total Response Time
- Queue Wait
- Interrupt Latency
- Turn Duration
- Error Rate
- Fallback Rate
- Dropped Input Count
- Out-of-order Event Count

## 十六、WebUI 可观察状态

至少显示：

```text
Runtime: Online / Offline

Conversation:
Idle / Receiving / Processing / Streaming / Interrupted

LLM:
Connected / Error

Memory:
Active / Error

Current Turn:
turn_id

TTFT:
xxx ms

Response:
Streaming / Complete / Error

最近错误：
xxx
```

## 十七、日志

每一个 Turn 必须通过 turn_id 找到完整链路。

关联：

```text
conversation_id
turn_id
request_id
model
provider
state transitions
latency
token usage
memory operation
error
fallback
interrupt
最终结果
```

日志必须能够回答：

- 为什么慢？
- 为什么没有回复？
- 为什么吃字？
- 为什么旧回答没有停止？
- 为什么新输入丢失？
- 为什么前端顺序错误？

## 十八、全链路测试

完整链路：

```text
用户输入
→ WebUI
→ Input Receiver
→ Turn Controller
→ Runtime
→ LLM
→ Streaming
→ SSE
→ WebUI Renderer
```

每个阶段必须单独可测试，再进行 Full Chain Test。

## 十九、必测场景

### Test 01
输入：你好

要求：快速自然返回。

### Test 02
连续 20 轮对话

要求：上下文稳定。

### Test 03
长回复

要求：持续 Streaming。

### Test 04
快速连续发送两条消息

要求：不丢消息。

### Test 05
模型生成过程中用户打断

要求：旧回复立即停止。

### Test 06
打断后继续新问题

要求：上下文不污染。

### Test 07
Streaming 中途异常

要求：不会永久卡住。

### Test 08
Provider 不支持 Streaming

要求：进入统一 Fallback。

### Test 09
SSE 网络异常

要求：前端明确进入错误/恢复状态。

### Test 10
页面重新连接

要求：Runtime 不产生重复 Turn。

### Test 11
长时间连续运行

要求：无明显内存增长、队列堆积或状态泄漏。

### Test 12
100轮对话

记录：

- TTFT
- 平均延迟
- P95 延迟
- 错误率
- 中断成功率
- 丢消息数量

## 二十、Demo 回归测试

必须保留 Demo 作为 Conversation Experience Baseline。

比较 Demo 与 Current Runtime：

- 首字延迟
- 首片延迟
- 输出连续性
- 句间卡顿
- 打断响应
- 连续输入
- 长回复体验
- 总响应时间

目标：

正式 Runtime 不得明显低于已经验证过的 Demo 交互体验。

## 二十一、改进原则

任何改动必须回答：

1. 解决什么问题？
2. 改动哪一层？
3. 是否影响现有 Streaming？
4. 是否影响 Memory？
5. 是否影响 Router？
6. 是否影响前端？
7. 如何回滚？
8. 如何测试？

## 二十二、热机功能启用顺序

```text
Phase 1 基础对话闭环
 ↓
Phase 2 Streaming稳定性
 ↓
Phase 3 Turn Controller
 ↓
Phase 4 Interrupt / Queue
 ↓
Phase 5 Observability
 ↓
Phase 6 Memory按需接入
 ↓
Phase 7 Model Router
 ↓
Phase 8 Token Optimization
 ↓
Phase 9 高级Agent能力
 ↓
Phase 10 多模态 / 具身能力
```

禁止基础对话未稳定时开启全部高级模块。

## 二十三、热机通过条件

必须同时满足：

- [ ] 可以正常输入
- [ ] 输入不会丢失
- [ ] 不会重复处理
- [ ] 首片快速出现
- [ ] Streaming连续
- [ ] 不明显吃字
- [ ] 输出结束明确
- [ ] 支持用户打断
- [ ] 打断后上下文不污染
- [ ] 连续消息不会丢失
- [ ] Streaming异常可以恢复
- [ ] 非Streaming Provider有Fallback
- [ ] WebUI状态真实
- [ ] 每个Turn可追踪
- [ ] 错误可以定位
- [ ] Runtime可以长期运行
- [ ] Demo交互体验不明显退化

## 二十四、失败判定

以下任一情况直接：

`NOT READY`

包括：

- 基础对话失败
- 输入丢失
- Streaming永久卡死
- 打断失效
- 上下文污染
- Turn状态失控
- 无法定位错误
- WebUI显示与实际状态不一致

不得用其他模块通过抵消基础对话失败。

## 二十五、Agent 执行要求

必须实际检查当前工程，而不是只给分析。

执行：

1. 读取现有 Conversation 相关代码；
2. 找到当前 Streaming 实现；
3. 找到 SSE 实现；
4. 找到前端接收逻辑；
5. 找到当前状态管理；
6. 找到已有 LatencyTracker；
7. 找到现有日志；
8. 找到现有测试；
9. 对照本 Prompt 检查缺口；
10. 优先复用现有实现；
11. 不重复创建已有功能；
12. 只修改必要代码；
13. 修改后运行测试；
14. 失败则定位并修复；
15. 最终生成热机改进报告。

## 二十六、禁止行为

禁止：

- 为了重构而重构
- 推倒已有 Streaming
- 重复实现日志
- 重复实现状态管理
- 删除 Demo 已验证机制
- 未测试直接宣称完成
- 用 Mock 结果冒充真实运行
- 为了测试通过而降低测试标准
- 基础对话未稳定时增加高级功能

## 二十七、最终返回格式

```text
YHLZ Heatup Improvement Report

当前版本：
xxx

修改内容：
xxx

保留的现有能力：
xxx

新增能力：
xxx

对话链路：
PASS / FAIL

Streaming：
PASS / FAIL

Turn Controller：
PASS / FAIL

Interrupt：
PASS / FAIL

Queue：
PASS / FAIL

Memory：
PASS / FAIL

Router：
PASS / FAIL

Observability：
PASS / FAIL

WebUI：
PASS / FAIL

Demo Regression：
PASS / FAIL

100轮测试：
PASS / FAIL

长时间运行：
PASS / FAIL

Blocking Issues：
xxx

回滚方案：
xxx

下一步：
xxx

最终状态：
READY / NOT READY
```

## 二十八、最终原则

YHLZ 热机不是追求功能最多。

而是追求每一层可靠。

对话不是一个 API 请求。

而是一个完整的 Conversation Turn。

Streaming 不是一个 UI 动画。

而是用户与元亨之间的实时交互通道。

Runtime 不是功能堆叠。

而是保证整个系统持续运行的核心。

最终目标：

```text
Stable Conversation Runtime
        ↓
Stable YHLZ Runtime
        ↓
高级智能能力验证
```

YHLZ

元 · 亨 · 利 · 贞

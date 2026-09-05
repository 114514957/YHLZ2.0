# ADR-001：Session Kernel 边界与双工模式

- 状态：Proposed
- 日期：2026-08-28
- 决策人：待指定
- 关联：`Session-Kernel-Protocol-v1_初稿.md`、`冻结前风险台账_初稿.md`

## 背景

YHLZ2.0 同时存在 `/chat`、`/ws/stream`、`/ws`、`/agent/chat`、独立语音 Demo 和多个外围服务。对话状态、播放状态、打断标志和记忆写入分布在不同模块。继续增加入口会放大 turn 竞态、旧音频泄漏、重复记忆和 Provider 绑定问题。

NEKO 的可借鉴部分是单点会话状态机、事件 fan-out，以及让 realtime/offline 客户端保持相同上层接口；其 Provider、前端和生命周期实现不适合直接移植到 YHLZ。

## 决策

1. 建立 `Session Kernel`，作为每个 session 唯一的 turn owner、状态真值和取消协调者；
2. 建立 `Conversation Coordinator`，只负责选择 Fast Path 或 Task Path，不拥有播放设备和数据库；
3. realtime、local pipeline、offline 和 Agent 通过 Adapter 接入同一协议；
4. 以事件封装中的 `session_id`、`turn_id`、`seq`、`trace_id` 作为跨模块关联基础；
5. 采用“语义全双工、能力可降级”：输入播放并行、抢占和 stale event 处理是公共语义，具体 Provider 能力通过协商决定；
6. 采用绞杀式迁移，旧入口先转为兼容适配器，验证后再废弃；
7. 暂不拆微服务，也不整体复制 NEKO 的 `LLMSessionManager`、Realtime Client、记忆和前端实现。

## 被否决的替代方案

### A. 原样搬运 NEKO 全双工代码

否决原因：依赖 OpenAI/Gemini Realtime 的事件和音频假设；与 YHLZ 的本地 ASR/LLM/TTS、Agent ReAct、现有播放队列不一致；会形成第二套状态机。当前 NEKO 实时客户端资料也不完整，无法安全承诺源码级兼容。

### B. 保留现有多入口，各自继续增强

否决原因：无法确定 turn 所有权，测试和故障恢复无法统一，技术债会继续固化。

### C. 一次性大重写

否决原因：当前缺少可运行环境和真实链路基线，无法证明新实现保留了现有可用行为，也没有可靠回滚点。

### D. 立即拆成全微服务

否决原因：单机单用户场景尚未证明需要分布式复杂度；先在模块化单体内建立契约，后续按资源和并发需求拆分。

## 结果和代价

### 正面结果

- 对话和打断语义统一；
- Provider、TTS、Avatar、Agent 可以独立替换或失败隔离；
- 事件可追踪、去重和回放；
- 新入口必须经过同一边界，复杂度增长受控。

### 必须接受的代价

- 初期会同时存在旧适配器和新 Kernel；
- 需要为事件、取消和能力协商增加测试与日志；
- 短期功能开发速度下降；
- 本地 Provider 可能只能提供半双工降级，而不是原生 realtime。

## 约束和不变量

- Kernel 不导入具体 ASR/LLM/TTS/数据库实现；
- 一个 session 同时只有一个活动 turn；
- 取消代际不匹配的输出不能提交；
- Memory 只有一个正式写入口；
- 任何外围模块都可以关闭而不破坏文本 Fast Path；
- 公共事件和状态改变必须通过 ADR 和契约测试。

## 通过条件

本 ADR 只有在以下证据齐备后才从 Proposed 变为 Accepted：

1. S0 运行环境可复现；
2. `/chat` 文本 Golden Path 有稳定特征测试；
3. `/ws` 和工具路由问题已有修复或废弃决定；
4. VAD、音频时钟、turn 提交和取消所有者已由 ADR-002 明确；
5. Memory Facade 和旧记忆迁移方案已由 ADR-003 明确；
6. 至少完成一次真实 Provider 的中断和恢复测试。

## 复审触发条件

出现以下任一情况时必须复审本 ADR：

- 需要多用户或跨机器部署；
- Provider 要求改变事件或会话语义；
- Agent 工具需要跨进程长任务；
- 记忆或音频数据需要外部服务；
- 全双工性能和资源指标无法在本机达到验收目标。

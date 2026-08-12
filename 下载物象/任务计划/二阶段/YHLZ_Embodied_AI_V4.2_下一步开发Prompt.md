# YHLZ Embodied AI V4.2 下一步开发 Prompt

> 本 Prompt 由 YHLZ Embodied AI V4.1 验收报告自动生成，供长期维护工程师启动 V4.2 阶段开发。
> 前置阶段：V4.1（Environment Intelligence Layer 环境理解层）已验收：专项 391/391，全量回归 Failed=0。

## 一、版本目标

**版本名**：YHLZ Embodied AI V4.2
**阶段主题**：环境推理增强层（Environment Reasoning Layer）
**一句话目标**：在 V4.1 环境理解（状态/记忆/反馈/预测）基础上，构建环境感知 → 事件归因 → 因果推断 → 语义环境的推理能力，并完成 Agent 深度集成与长期记忆。

## 二、开发任务

### P0（必做）

1. **Environment Event Log（环境事件日志，可选持久化）**
   - 为 MockEnvironment 增加事件日志（动作 / 结果 / 对象状态变化 / 主体位置 / 时间线）
   - 支持按时间 / 类型 / 对象查询，提供 `get_events()` / `event_history()` 查询接口
   - 可选 JSONL 落盘（配置 `embodied_event_log_path`），默认内存缓冲

2. **Feedback Causal Analysis（反馈因果归因分析）**
   - FeedbackAnalyzer 升级：除 success / failure / suggestion 外，输出 `cause`（归因：环境状态 / 动作参数 / 权限 / 预测偏差）
   - 规则表扩展：pick 失败归因"位置不匹配"，move 越界归因"边界限制"，place 失败归因"持有状态缺失"等
   - 输出新增 `cause: str` 字段（保持旧字段兼容）

3. **State Predictor 升级（状态预测 → 条件预测）**
   - 支持"条件预测"：给定动作序列（多步），预测最终状态（如 MOVE+PICK → object=held）
   - 支持状态不变式检测（如 door 打开后不会自行关闭）
   - 保持规则驱动（禁止 AI 训练），verify 增加 `step_verified` 列表

4. **Agent 深度集成（行为工具）**
   - 新增工具 `query_environment_events`（查询事件历史，只读）
   - 新增工具 `predict_environment_change`（提交动作 → 返回预测结果，只读，不执行）
   - `build_environment_context()` 增加：事件摘要 / 因果分析摘要 / 预测置信度提示

5. **长期环境记忆（Embodied 持久化）**
   - EnvironmentMemory 支持跨进程持久化（启动加载 `embodied_memory_path`，关闭保存，JSONL）
   - 增加摘要能力：`summary()` 输出高频失败模式 / 成功率趋势

### P1（应做）

6. **多环境动态切换（场景生命周期）**
   - 支持运行中注册 / 注销环境（已具备），增加 `switch_environment(name)` 安全切换（切换前自动 observe + 记录事件）
   - 场景间迁移：切换后 WorldModel 自动 reset 并建立新场景首状态

7. **目标回放（Goal Replay）**
   - 保存每次目标执行轨迹（plan / executed / feedback / analysis），支持 `replay_goal(goal_id)` 回放与对比
   - 输出执行时间线（Observe → Action → Feedback 时间点）

8. **具身状态报告 API**
   - Service 增加 `report()`：汇总世界模型 / 记忆 / 反馈 / 预测 / 事件的全量状态（供管理界面 / Agent 长对话使用）

### 安全与工程约束（沿用）

- `embodied_enabled=False` 默认关闭；流程固定 `Observe → Reasoning → Permission → Action → Feedback`；无环境 → 直接执行错误
- 禁止：真实设备控制 / 机器人控制 / 自动驾驶 / AI 训练式预测 / 修改 Agent Brain / 修改 Vision Interface / 修改 Memory Interface / 自我目标生成 / 未授权动作
- World Model 与预测器禁止直接执行 Action（必须经 Permission → Executor）
- 规则驱动优先（确定性与可测试性）；如未来引入 LLM 推理必须配置开关 + Mock 优先
- 类型注解完整、中文注释、完整日志、RLock、单例 + reset、异常隔离、配置驱动（`embodied_*`）
- 与既有模块完全隔离（不污染 Agent Memory / Vision / Personality / Action）

## 三、验收标准

### 测试

```powershell
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests -v
```

- 专项用例 ≥ 450（V4.1 为 391），Failed = 0
- 全量回归 Failed = 0：
  ```powershell
  $env:YHLZ_UNDERSTANDING_TEST_MODE="true"
  # Action / Personality / Agent / Vision(全四子集) 全部通过
  ```

### 功能验收点

- [ ] 事件日志可查询（按时间 / 类型 / 对象），可选落盘
- [ ] 反馈分析输出 cause 归因（5+ 归因规则），旧字段兼容
- [ ] 多步条件预测成功（MOVE+PICK → held），verify 输出 step_verified
- [ ] 新工具注册（query_environment_events / predict_environment_change）可调用且只读
- [ ] 环境记忆跨进程持久化（保存 → 重新加载 → 数据一致）
- [ ] 场景切换安全（自动观察 + 记录 + WorldModel 重建）
- [ ] 目标回放可用（轨迹保存 → 回放 → 对比）
- [ ] 默认关闭 / Mock 优先 / 硬件禁用 / 异常隔离
- [ ] 未破坏既有模块（全量回归）

## 四、报告要求

按 V4.1 验收报告模板输出 `YHLZ_Embodied_AI_V4.2_验收报告.md`（版本信息 / 执行总结 / 代码修改记录 / 测试报告 / 架构影响分析 / 问题复盘 / 下一阶段规划），并生成 `YHLZ_Embodied_AI_V4.3_下一步开发Prompt.md`。

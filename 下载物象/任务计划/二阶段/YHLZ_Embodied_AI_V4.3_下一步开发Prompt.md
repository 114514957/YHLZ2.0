# YHLZ Embodied AI V4.3 下一步开发 Prompt

> 本 Prompt 由 YHLZ Embodied AI V4.2 验收报告自动生成，供长期维护工程师启动 V4.3 阶段开发。
> 前置阶段：V4.2（Environment Reasoning Layer 环境推理层）已验收：专项 568/568，全量回归 Failed=0。

## 一、版本目标

**版本名**：YHLZ Embodied AI V4.3
**阶段主题**：经验学习层（Experience Learning Layer）
**一句话目标**：在 V4.2 环境推理（事件时间线 / 因果归因 / 多步预测 / 不变式 / 语义环境）基础上，构建"经验沉淀 → 策略学习 → 场景生命周期"能力：补齐 V4.2 P1 三项（场景切换 / 目标回放 / 状态报告），并将失败经验与成功轨迹转化为可复用的规则化策略，形成闭环的经验学习层。

## 二、开发任务

### P0（必做）

1. **V4.2 P1 回补：多环境动态切换（场景生命周期）**
   - `switch_environment(name)` 安全切换：切换前自动 observe + 记录 RESET 事件 + 事件时间线场景分段（每段标记场景名）
   - 切换后 WorldModel 自动 reset 并建立新场景首状态；切换期间 Permission 前置校验
   - 支持运行中注册 / 注销环境（沿用 V4.1 注册表），`list_environments()` 只读查询

2. **V4.2 P1 回补：目标回放（Goal Replay）**
   - 每次目标执行保存完整轨迹（goal / plan / executed actions / feedback / analysis / 事件时间线 / 最终状态）
   - `replay_goal(goal_id)` 回放：输出逐步骤时间线（Observe → Action → Feedback 时间点）、每步 success/failure、最终目标达成状态
   - `compare_goals(goal_id_a, goal_id_b)` 对比：步骤数 / 失败点 / 耗时 / 达成结果差异

3. **V4.2 P1 回补：具身状态报告 API**
   - Service `report()`：汇总世界模型 / 记忆 / 反馈 / 预测 / 事件 / 场景 / 经验策略的全量状态（字典结构，供管理界面与 Agent 长对话）

4. **经验学习（规则驱动，禁止 AI 训练）**
   - **失败策略沉淀**：基于 experience_summary 的失败模式 + CausalAnalyzer 归因，生成规则化策略表（如：pick 连续 2 次失败 → 策略"先 scan/inspect 确认对象位置"；move 越界 → 策略"先 query_environment_state 确认边界"）
   - **成功策略沉淀**：目标成功轨迹提炼为"成功配方"（action 序列模板 + 前置条件），供同类型目标复用参考
   - 策略表持久化（JSONL，配置 `embodied_policy_path`），跨进程加载；`policy_stats()` 输出命中率 / 生效次数

5. **策略应用到规划（弱耦合，不改 Agent Brain）**
   - `run_goal` 前查询策略表：匹配的失败策略作为"预警提示"注入 analysis.suggestion；匹配的成功配方作为 plan 初始模板（仍可被安全层拒绝）
   - 策略应用全程规则驱动 + 可解释（输出"依据策略 #id 命中"），默认关闭策略注入（配置 `embodied_policy_enabled`，默认 false）

### P1（应做）

6. **场景迁移认知**
   - 场景切换后 `build_environment_context()` 输出场景段摘要（本场景事件数 / 失败数 / 活跃对象），Agent 可感知场景边界
   - 跨场景对象变化检测：切换前后同名对象状态差异摘要

7. **经验质量指标**
   - 策略命中率统计：策略被建议次数 vs 被采纳（导致成功）次数；低效策略自动降级标记
   - 目标成功率趋势按场景 / 目标类型分组（`trend_by_scene` / `trend_by_goal_type`）

8. **轨迹导出**
   - `export_goal_trace(goal_id)`：将目标轨迹导出为结构化文本 / JSON（供验收演示与故障复盘）

### 安全与工程约束（沿用）

- `embodied_enabled=False` 默认关闭；流程固定 `Observe → Reasoning → Permission → Action → Feedback`；无环境 → 直接执行错误
- 禁止：真实设备控制 / 机器人控制 / 自动驾驶 / AI 训练式学习 / 修改 Agent Brain / 修改 Vision Interface / 修改 Memory Interface / 自我目标生成 / 未授权动作
- 经验学习必须是**规则化策略**（表驱动 / 模板匹配），严禁任何模型训练、梯度更新、黑盒预测；策略注入仅影响建议与规划模板，绝不绕过 Permission
- World Model 与预测器禁止直接执行 Action（必须经 Permission → Executor）
- 类型注解完整、中文注释、完整日志、RLock、单例 + reset、异常隔离、配置驱动（`embodied_*`）
- 与既有模块完全隔离（不污染 Agent Memory / Vision / Personality / Action）

## 三、验收标准

### 测试

```powershell
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests -v
```

- 专项用例 ≥ 620（V4.2 为 568），Failed = 0
- 全量回归 Failed = 0：
  ```powershell
  $env:YHLZ_UNDERSTANDING_TEST_MODE="true"
  # Action / Personality / Agent / Vision(全四子集) 全部通过
  ```

### 功能验收点

- [ ] `switch_environment(name)` 切换安全（自动 observe + RESET 事件 + 世界模型重建），时间线场景分段
- [ ] `replay_goal(goal_id)` 轨迹回放（步骤时间线 + 逐步成败 + 最终达成），`compare_goals` 对比可用
- [ ] `report()` 全量状态报告（世界模型 / 记忆 / 反馈 / 预测 / 事件 / 场景 / 策略）
- [ ] 失败策略沉淀：模拟 2 次同因失败 → 策略表生成 → 下次 run_goal 注入预警建议
- [ ] 成功配方沉淀：成功轨迹 → 配方模板 → 同类型目标 plan 复用（默认关闭注入，开启后仍可被安全层拒绝）
- [ ] 策略持久化跨进程一致（保存 → 加载 → 命中率数据保留）
- [ ] 默认关闭 / Mock 优先 / 硬件禁用 / 异常隔离 / 策略注入默认关闭
- [ ] 未破坏既有模块（全量回归 Failed=0）

## 四、报告要求

按 V4.2 验收报告模板输出 `YHLZ_Embodied_AI_V4.3_验收报告.md`（版本信息 / 执行总结 / 代码修改记录 / 测试报告 / 架构影响分析 / 问题复盘 / 下一阶段规划），并生成 `YHLZ_Embodied_AI_V4.4_下一步开发Prompt.md`。

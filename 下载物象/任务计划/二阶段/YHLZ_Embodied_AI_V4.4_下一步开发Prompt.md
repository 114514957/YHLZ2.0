# YHLZ Embodied AI V4.4 下一步开发 Prompt

> 本 Prompt 由 YHLZ Embodied AI V4.3 验收报告自动生成，供长期维护工程师启动 V4.4 阶段开发。
> 前置阶段：V4.3（Experience Learning Layer 经验学习层）已验收：专项 798/798，全量回归 Failed=0
> （Embodied 798 + Vision 136 + Action 151 + Personality 137 + Agent 131 + voice_identity 181 全部通过）。

## 一、版本目标

**版本名**：YHLZ Embodied AI V4.4
**阶段主题**：自适应策略层（Adaptive Strategy Layer）
**一句话目标**：在 V4.3 经验学习（失败策略 / 成功配方 / Policy Table / 场景生命周期 / 目标回放 / 状态报告）基础上，构建"策略自我进化"能力：策略按场景与目标类型自适应调度、质量持续评估与自动恢复、策略生命周期管理（归档 / 淘汰 / 版本化）、趋势统计与决策审计，使经验层从"记录 + 复用"升级为"评估 + 进化"的闭环。

**本版本不引入 AI 训练**：所有自适应机制仍为规则表 + 统计阈值驱动（命中率排序、场景分组、时效衰减），保持可解释性与确定性。

## 二、开发任务

### P0（必做）

1. **策略自适应调度（按场景 / 目标类型分组）**
   - Policy Table 增加分组维度：`scene`（room / warehouse / 自定义）与 `goal_type`（pick / move / place / inspect / scan）
   - `suggest_for_goal` 升级：同一 trigger 多场景策略共存时，按当前场景优先匹配；无场景策略时回退通用策略
   - 同组策略竞争时按质量排序（hit_rate 高者优先，其次 acceptance_rate，其次较新），输出排序依据（可解释）

2. **策略质量持续评估与自动恢复（degraded 恢复）**
   - 已降级策略在"新场景 / 参数环境变化"后可重新评估（冷启动恢复窗口：连续 N 次建议且有采纳且成功 → 自动解除 degraded）
   - 质量评估加入时效因子：策略超过 `embodied_policy_max_age_days` 无采纳记录 → 标记 `stale`（不参与建议，可归档）
   - `policy_stats()` 增加：`stale_count` / `archived_count` / `recovered_count` / `by_scene` / `by_goal_type`

3. **趋势统计（V4.3 P1 回补）**
   - 目标成功率趋势：`trend_by_scene`（按场景分组成功率曲线）、`trend_by_goal_type`（按目标类型分组）
   - 数据来源：GoalTraceStore 全部轨迹（success / failures / duration），输出固定窗口（近 10 次）滚动成功率
   - 新增 `trend_stats()` API + `report()` 中输出趋势摘要

4. **策略生命周期管理**
   - `archive_policy(trigger)`：归档（不删除、不再建议、可 `restore_policy(trigger)` 恢复）
   - 策略版本化：同一 trigger 每次策略内容更新记录版本号（`version` + `updated_at`），`policy_history(trigger)` 可查历史版本（内存内保留最近 N 版）
   - `clear_policies()` 全量清空（含归档），供配置重置

5. **决策审计日志（可解释性强化）**
   - 每次策略应用（template 应用 / warning 注入 / 排序命中）写入独立审计记录（与 Agent Memory 完全隔离）：
     `{timestamp, goal_id, trigger, kind, action, scene, applied: bool, reason}`
   - `audit_policy_log(limit)` 查询；`report()` 输出最近审计摘要（应用次数 / 拒绝次数）

### P1（应做）

6. **事件时间线场景分段**
   - `event_history()` / 轨迹 `event_timeline` 增加 `scene_segment` 标记（切换后事件归属场景段 id），目标回放可展示跨场景轨迹分段
   - `replay_goal()` 输出增加 `scene_segments`（每段：场景名 / 起始步骤 / 事件数 / 失败数）

7. **策略预演（dry-run）**
   - `suggest_for_goal(goal, plan, dry_run=True)`：只返回将应用的策略与计划替换结果，不写统计、不改计划（验收演示用）

8. **成功配方参数泛化**
   - 配方 `action_sequence` 参数归一化（move 的 dx/dy 相对化：记录方向与符号，不锁定绝对值），跨场景复用成功率提升
   - 配方增加 `applicable_scenes` 推断（配方来源场景 + 前置条件匹配）

### 安全与工程约束（沿用，新增强调）

- `embodied_enabled=False` 默认关闭；流程固定 `Observe → Reasoning → Permission → Action → Feedback`；无环境 → 直接执行错误
- 禁止：真实设备控制 / 机器人控制 / 自动驾驶 / AI 训练式学习 / 修改 Agent Brain / 修改 Vision Interface / 修改 Memory Interface / 自我目标生成 / 未授权动作
- 自适应必须是**规则 + 统计阈值驱动**（命中率排序 / 场景分组 / 时效衰减 / 冷启动恢复），严禁模型训练、梯度更新、黑盒预测；策略仅影响建议与规划模板，绝不绕过 Permission
- 新增策略生命周期操作（归档 / 恢复 / 清空）均为显式 API 调用，不做隐式自动删除
- 类型注解完整、中文注释、完整日志、RLock、单例 + reset、异常隔离、配置驱动（`embodied_*`）
- 与既有模块完全隔离（不污染 Agent Memory / Vision / Personality / Action）；审计日志独立存储
- 新配置项：`embodied_policy_max_age_days`（默认 30）、`embodied_policy_recovery_window`（默认 3）、`embodied_policy_history_max`（默认 5）

## 三、验收标准

### 测试

```powershell
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests -v
```

- 专项用例 ≥ 850（V4.3 为 798），Failed = 0
- 全量回归 Failed = 0：
  ```powershell
  # Vision / Action / Personality / Agent / voice_identity 全部通过
  ```

### 功能验收点

- [ ] 场景 / 目标类型分组策略并存与优先匹配（同 trigger 多场景策略正确路由）
- [ ] degraded 策略冷启动恢复（条件满足自动解除）与 stale 标记（超龄无采纳）
- [ ] `trend_by_scene` / `trend_by_goal_type` 滚动成功率曲线正确
- [ ] 归档 / 恢复 / 版本历史（`policy_history`）可用，归档策略不再建议
- [ ] 决策审计日志完整（应用 / 拒绝均可追溯原因），与 Agent Memory 隔离
- [ ] 事件时间线场景分段 + 跨场景回放（`scene_segments`）
- [ ] dry-run 不写统计不改计划
- [ ] 默认关闭 / Mock 优先 / 硬件禁用 / 异常隔离
- [ ] 未破坏既有模块（全量回归 Failed=0）

## 四、报告要求

按 V4.3 验收报告模板输出 `YHLZ_Embodied_AI_V4.4_验收报告.md`（版本信息 / 执行总结 / 代码修改记录 / 测试报告 / 架构影响分析 / 问题复盘 / 下一阶段规划），并生成 `YHLZ_Embodied_AI_V4.5_下一步开发Prompt.md`。

# YHLZ Embodied AI V4.6 验收报告

> 版本：V4.6.0（Cross-Goal Strategic Planning 跨目标战略规划层）
> 日期：2026-08-07
> 项目根：`D:\YHLZ2.0`；工作区：`backend/embodied/`
> 前置：V4.5 已验收（embodied 1078 / 全量 1814, Failed=0）

---

## 一、完成状态

| 项目 | 状态 |
|---|---|
| V4.6 跨目标战略规划（Cross-Goal Strategic Planning） | ✅ 完成 |
| V4.6 专项测试 | ✅ 94 用例（专项合计 1172） |
| 全量回归（embodied） | ✅ 1172 tests, Failed=0 |
| 跨子系统回归（Vision/Action/Agent/Personality/voice_identity） | ✅ 全部 Failed=0 |
| 验收报告 | ✅ 本文档 |
| 下一阶段 Prompt | ✅ `YHLZ_Embodied_AI_V4.7_下一步开发Prompt.txt` |

**核心能力跃迁：** AI 管理策略体系（V4.5）→ **AI 跨目标统筹规划**（V4.6）。
从单目标智能体进入多目标战略智能体，保持纯规则 + 统计 + 阈值 + 可解释排序，无任何 NN 训练 / 黑盒优化。

---

## 二、修改内容

### 2.1 新建规划包 `backend/embodied/planning/`

| 文件 | 内容 |
|---|---|
| `dependency.py` | `GoalDependencyAnalyzer`：目标分组（scene×goal_type×action_sequence）/ 共享步骤识别 / 信息复用分析；`plan_action_sequence` / `infer_goal_type_of` 独立动作推导 |
| `budget.py` | `BudgetAllocator`：单目标基础需求（计划长度/max_steps/关键词默认）/ 需求计算（含共享节省）/ 预算分配（按需 or 权重比例）/ 预算冲突检测（降级建议） |
| `cross_goal.py` | `CrossGoalPlanner` 门面：分组 → 组间排序（优先级+组大小）→ 共享步骤 → 预算分配 → 战略规划输出（`CrossGoalPlan`）+ 策略质量查询 |
| `__init__.py` | 包导出（全部符号 + 门面） |

**CrossGoalPlan 数据模型**（与 v4.6.txt 一致）：
```
{ plan_id, goals, groups, shared_steps, budget_allocation,
  explainable_reason, mode: "rule_based" }
```

### 2.2 配置驱动 `backend/config.py`

新增 7 项配置（`embodied_planning_*` 前缀 + `EMBODIED_PLANNING_*` 环境变量）：
- `embodied_planning_enabled`（默认 false，权限默认拒绝）
- `embodied_planning_max_budget`（默认 100）
- `embodied_planning_min_group_size`（默认 2）
- `embodied_planning_priority_weight_high/medium/low`（2.0/1.5/1.0）
- `embodied_planning_min_steps_per_goal`（默认 1）

### 2.3 Service 新增 4 个 V4.6 API（V4.5 API 全部不变）

| API | 功能 |
|---|---|
| `cross_goal_plan(goals, budget)` | 跨目标规划主入口（含审计 cross_goal） |
| `cross_goal_groups(goals)` | 目标分组分析 |
| `cross_goal_budget(goals, budget)` | 预算分配（自定义 budget 支持） |
| `cross_goal_dry_run(goals)` | 规划预演（不写审计 + 保护规则检查） |

### 2.4 其他修改
- `backend/embodied/strategy/audit.py`：AUDIT_ACTIONS 新增 `cross_goal` 动作（V4.6 规划追踪）
- `backend/embodied/__init__.py`：`__version__ = "4.6.0"` + planning 包导出
- `backend/embodied/service.py`：版本升 4.6.0 + `planner` 懒加载 property + load_config 构造规划器
- `backend/embodied/governance/__init__.py`：status() 版本 4.6.0

### 2.5 新增测试文件（3 个，94 用例）

| 文件 | 覆盖 | 用例数 |
|---|---|---|
| `tests/test_planning_dependency.py` | 动作序列映射/目标分组/共享步骤/信息复用/只读验证 | 38 |
| `tests/test_planning_budget.py` | 基础需求/需求计算/预算分配/质量加成/冲突检测/参数校验 | 27 |
| `tests/test_planning_cross_goal.py` | 规划器结构/分组排序/预算冲突/质量查询/Service 4 API/审计/安全/兼容 | 29 |

---

## 三、测试结果

### 3.1 Embodied 专项（验收命令）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 指标 | 数值 |
|---|---|
| Total | **1172**（≥1138 ✅） |
| Passed | 1172 |
| Failed | **0** ✅ |
| Skipped | 0 |

其中 V4.6 新增规划专项 94 用例全部通过。

### 3.2 全量回归（跨子系统）

| 子系统 | Total | Failed |
|---|---|---|
| embodied | 1172 | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **1908** | **0** ✅ |

---

## 四、V4.6 能力验收对照（v4.6.txt）

| 需求 | 实现 | 状态 |
|---|---|---|
| 一、目标分组分析（相同 scene+goal_type+action_sequence） | `analyze_groups()` 组输出含 member_count/goal_ids/batch_plan | ✅ |
| 二、共享步骤识别（一次 scan 服务多目标） | `shared_steps()` 前置 scan/observe/explore → saved_steps + 可解释 reason | ✅ |
| 三、跨目标预算分配（策略质量+优先级+资源限制，可解释） | `allocate()` 需求≤预算按需 / 需求>预算权重比例；质量加成（hit_rate≥阈值）；每条含 reason | ✅ |
| 四、cross_goal_plan() 完整规划输出 | CrossGoalPlan（plan_id/goals/groups/shared_steps/budget_allocation/explainable_reason/mode） | ✅ |
| 五、测试 ≥60 cases / 专项 ≥1138 | 新增 94 用例，专项 1172 | ✅ |
| P1 跨目标策略复用统计 | 审计 `cross_goal` 动作记录一次规划服务 N 目标；信息复用分析 | ✅ |
| P1 规划冲突检测（预算不足→降级建议） | `detect_conflict()` 缺口 + 低优先级降级建议（可解释） | ✅ |
| P1 Cross Goal Dry Run | `cross_goal_dry_run()` 复用 SystemSnapshot 风格（保护规则检查 + 不写审计） | ✅ |
| 配置驱动 | 全部 embodied_planning_* + EMBODIED_* 环境变量 | ✅ |
| 安全约束 | 规划不写 Agent Memory / 不绕过 Permission / 不控制设备 / 纯规则 | ✅ |

---

## 五、问题与风险

### 5.1 已解决问题（开发中发现并修复）
| 问题 | 修复 |
|---|---|
| 分组签名含 target → 同场景同类型目标无法成组 | 分组维度改为仅动作类型序列 |
| 多关键词目标只生成单动作（"扫描再拿起"→仅 scan） | `plan_action_sequence` 按关键词收集全部动作 |
| 预算充足时权重比例分配与实际 allocated 不一致 | 需求≤预算按需分配；需求>预算权重比例（可解释 reason 与结果一致） |
| 共享节省均摊 `1//2=0` 导致节省丢失 | 均摊 + 余数按序分配 |

### 5.2 已知遗留（低风险）
| 问题 | 影响 | 处置 |
|---|---|---|
| `plan_action_sequence` 与 Service.plan_actions 是两套独立规则实现 | 潜在不一致 | 当前规则一致（关键词映射），后续可统一为单一推导源 |
| 跨目标规划为纯方案输出（不自动执行） | 符合本阶段边界 | V4.7 Long Horizon Planning 可衔接执行编排 |
| 共享节省按"均摊到成员"近似 | 与精确组级步骤有 ±1 步误差 | 语义可解释（每成员减 saved/members 步），可接受 |

### 5.3 未来风险
- **预算分配的整型取整**：权重比例分配向下取整，极小预算下高/低优先级差距可能被 min_steps 拉平
- **分组依赖 intent 字段**：intent 缺失时用动作序列兜底，跨语言描述（纯中文）时分组粒度可能偏粗

---

## 六、架构影响

| 维度 | 说明 |
|---|---|
| 影响模块 | 新建 `embodied/planning/`；修改 `embodied/service.py`、`embodied/strategy/audit.py`、`embodied/__init__.py`、`backend/config.py` |
| 兼容情况 | V4.5 全部 API 签名不变（向后兼容）；版本统一升 4.6.0；V4.3 JSONL 数据兼容 |
| 分层 | `CrossGoalPlanner` 经 Service 唯一接入；planning 只依赖 schema/policy/audit，不跨层 |
| 扩展能力 | 分组维度 / 共享动作类型 / 优先级权重 / 质量阈值全部可配置；审计动作白名单可扩展 |
| 无侵入 | 未改 Agent Brain / Vision / Memory Interface；规划只输出方案不执行；不写 Agent Memory |

---

## 七、下一阶段建议

见 `YHLZ_Embodied_AI_V4.7_下一步开发Prompt.txt`（Long Horizon Planning Layer 长期任务规划与战略执行管理）。

V4.6 使 YHLZ 从 **单目标智能体** 进入 **多目标战略智能体**：
- 能"看"多目标全貌（分组分析）
- 能"统筹"（共享步骤识别 + 预算分配）
- 能"预演"（Cross Goal Dry Run + 保护规则）
- 能"追踪"（跨目标规划审计）
- 全程可解释、可审计、纯规则驱动

# YHLZ Embodied AI 架构设计白皮书

> 版本：V5.4.0（Companion Self-Correction & Learning）
> 日期：2026-08-07
> 项目根：`D:\YHLZ2.0`；工作区：`backend/embodied/`
> 测试基线：embodied 1815 tests / 全量 2551 tests, Failed=0

---

## 目录

1. 系统概述
2. 总体架构
3. 能力层详解（V4.0 ~ V5.4）
4. 核心数据模型
5. 完整智能闭环（数据流）
6. 安全约束体系
7. 配置驱动体系
8. 测试体系
9. 演进路径与未来方向

---

## 一、系统概述

YHLZ 是一个多模态 AI 智能体伙伴，其 Embodied 子系统从 V4.0 到 V5.4 建立了完整的
**规则驱动具身智能**架构。核心哲学：

```
纯规则 + 统计 + 阈值 + 可解释排序 + 确定性流程
```

**禁止**：神经网络训练 / 梯度更新 / 黑盒优化 / 自主修改策略内容 / 自我目标生成。

能力进化链：

```
V4.0 AI 能行动       → V4.1 AI 理解环境
    → V4.2 AI 理解原因 → V4.3 AI 积累经验
    → V4.4 AI 选择最佳经验 → V4.5 AI 管理策略体系
    → V4.6 AI 跨目标统筹规划 → V4.7 AI 管理长期任务
    → V5.0 AI 内部多智能体协作 → V5.1 AI 伙伴协同增强
    → V5.2 AI 感知-策略闭环 → V5.3 AI 执行-反馈闭环
    → V5.4 AI 自我修正与学习
```

---

## 二、总体架构

### 2.1 分层架构（铁律）

```
Interface (Agent / FastAPI / 外部调用)
    ↓
Service (EmbodiedService, 唯一对外 API 入口)
    ↓
Manager (EmbodiedManager: 注册 / 路由 / 生命周期)
    ↓
Storage / Adapter (WorldModel / Memory / 环境适配器)
```

**禁止跨层调用**：Adapter 不调 Service；Manager 不直接暴露给外部；
Service 是唯一对外 API 入口。

### 2.2 子系统独立性

| 子系统 | 目录 | 依赖 |
|---|---|---|
| Environment | `environment/` | 无（自包含） |
| Reasoning | `reasoning/` | schema |
| World Model | `world_model/` | schema |
| Experience | `experience/` | schema, strategy |
| Strategy | `strategy/` | schema |
| Governance | `governance/` | experience, strategy |
| Planning | `planning/` | schema, experience, strategy |
| Companion | `companion/` | schema + Service 能力方法 |
| Feedback | `feedback/` | schema |

跨子系统协作只能通过 Tool System 或 Service 层 API。

### 2.3 模块全景

```
backend/embodied/
├── environment/    环境基础层 (V4.0): interface/mock/registry/adapter
├── world_model/    世界模型 (V4.1): state/memory/predictor
├── reasoning/      环境推理 (V4.2): cause/event_log/invariants/semantics
├── feedback/       反馈闭环 (V4.0~4.3): analyzer/processor
├── experience/     经验学习 (V4.3~4.4): learner/patterns/policy
├── strategy/       自适应策略 (V4.4): audit/ranker/trends
├── governance/     元策略治理 (V4.5): overview/governance/evolution/health/dry_run
├── planning/       跨目标+长期规划 (V4.6~4.7): cross_goal/budget/dependency/
│                   milestone/dependency_graph/progress_tracker/adjustment/long_horizon
├── companion/      伙伴架构 (V5.0~5.4): specialist/router/delegate/main_agent/
│                   stats/pipeline/executor/correction/learning
├── service.py      统一 Service (唯一入口)
├── manager.py      统一 Manager
├── schema.py       数据模型
├── permission.py   权限系统
├── config.py       (backend/config.py) 全局配置
└── tests/          测试套件
```

---

## 三、能力层详解

### 3.1 V4.0 Environment Foundation 环境基础层

- **Environment 接口**：`observe / execute_action / get_state / reset`
- **MockEnvironment**：虚拟网格世界（绝对安全，测试默认）
- **HardwareEnvironment**：真实设备适配（默认不启用）
- **PermissionChecker**：默认拒绝（`embodied_enabled=False`）
- **闭环**：`Observe → Reasoning → Permission → Action → Feedback`

### 3.2 V4.1 Environment Intelligence 环境理解层

- **WorldModel**：状态历史 + 差异分析（`state_changes`）
- **StatePredictor**：单步/多步条件预测（规则推演，不执行）
- **FeedbackAnalyzer**：反馈 → 建议 → 自适应调整
- **build_environment_context**：供 Agent 推理的完整上下文

### 3.3 V4.2 Environment Reasoning 环境推理层

- **EnvironmentEventLog**：事件时间线（action/object_change/move/failure）
- **CausalAnalyzer**：失败因果（position_mismatch/boundary_limit/object_missing…）
- **InvariantChecker**：状态不变式检测
- **SemanticAnalyzer**：语义环境理解

### 3.4 V4.3 Experience Learning 经验学习层

- **ExperienceLearner**：`on_action_result / on_goal_complete`
- **PatternExtractor**：失败模式提取（规则表）
- **PolicyTable**：策略表（trigger → strategy，JSONL 持久化）
- **GoalReplay**：目标轨迹回放（GoalTraceStore）
- **SceneManager**：场景生命周期（switch_environment）

### 3.5 V4.4 Adaptive Strategy 自适应策略层

- **PolicyTable 增强**：`scene × goal_type × kind` 调度维度
- **PolicyRanker**：可解释质量排序（hit_rate/acceptance/recency 权重）
- **生命周期**：active / degraded / stale / archived（恢复机制）
- **版本化**：`upsert_version`（同 trigger 多版本，独立统计）
- **PolicyAuditLog**：独立审计日志（suggest/apply/reject/rank/…）
- **TrendStats**：场景/目标成功率趋势
- **Dry Run**：`dry_run_suggestion` 只模拟不写统计

### 3.6 V4.5 Meta Strategy Management 元策略管理层

`governance/` 包（门面 `StrategyGovernance`）：

| 模块 | 职责 |
|---|---|
| `overview.py` | `strategy_system_overview`：策略矩阵（scene×goal_type×kind）+ 质量 + 一致性检查（同一 trigger 单 active） |
| `governance.py` | 冗余检测（同维度同内容）/ 冲突检测（多 active 版本）/ 低效归档（年龄+hit_rate 阈值，人工确认）/ 回收站（delete→restore→purge） |
| `evolution.py` | 同化 consolidate（Policy Family 共享父级统计）/ 分裂 split（按 scene/goal_type）/ 版本比较 / 回滚（仅 regression） |
| `health.py` | `policy_health_check`（healthy/weak/stale/conflict/redundant + 评分）/ `scene_coverage` |
| `dry_run.py` | `governance_dry_run` 统一入口 + SystemSnapshot（快照差异）+ 保护规则检查 |

**治理动作只影响**：策略表 → 审计日志 → 体系快照。

### 3.7 V4.6 Cross-Goal Strategic Planning 跨目标战略规划层

`planning/` 包（门面 `CrossGoalPlanner`）：

| 模块 | 职责 |
|---|---|
| `dependency.py` | 目标分组（scene×goal_type×action_sequence）/ 共享步骤识别（一次 scan 服务多目标）/ 信息复用 |
| `budget.py` | 需求计算（计划长度/max_steps/共享节省）/ 预算分配（需求≤预算按需，>预算权重比例）/ 冲突检测（降级建议） |
| `cross_goal.py` | 分组 → 排序（优先级+组大小）→ 预算 → CrossGoalPlan（plan_id/goals/groups/shared_steps/budget_allocation/explainable_reason） |

### 3.8 V4.7 Long Horizon Planning 长期任务规划层

`planning/` 包（门面 `LongHorizonPlanner`）：

| 模块 | 职责 |
|---|---|
| `milestone.py` | LongGoal（6 状态机）/ Milestone（5 状态机 + 迁移校验）/ 目标分解（任务树） |
| `dependency_graph.py` | 依赖设置（存在性/循环检测）/ 依赖图（前置/后续/阻塞原因）/ 拓扑排序 |
| `progress_tracker.py` | 进度跟踪（Goal 60% / Completed 3/5 / Blocked / Next）/ 快照 + 断点恢复（按 order 跨会话映射） |
| `adjustment.py` | 计划调整（4 触发条件 → 方案，permission_required）/ 风险预测（low/medium/high）/ 时间规划（deadline） |
| `long_horizon.py` | 门面：create/decompose/generate_milestones/track/adjust/risk/time/snapshot/dry_run |

### 3.9 V5.0 Adaptive Companion Architecture 伙伴架构

`companion/` 包（门面 `MainCompanionAgent`）：

| 模块 | 职责 |
|---|---|
| `specialist.py` | SpecialistRegistry（注册/查询/启停）+ SpecialistAgent（invoke 异常隔离） |
| `router.py` | 意图关键词 → 能力域确定性路由 + 回退默认委派 |
| `delegate.py` | 路由 → 委派 → 汇总（CompanionResponse） |
| `main_agent.py` | 统一入口/统一人格（铁哥们）/统一决策中心 |

**6 能力域**：perception / reasoning / experience / planning / long_horizon / governance。

**一个人格 / 一个核心意识 / 一个决策中心**：专业 Agent 无独立人格。

### 3.10 V5.1 Companion Coordination Enhancement 协同增强

- **router 增强**：关键词权重打分（复合 3.0/核心 2.0/默认 1.0）+ Top-K 路由（可配置）
- **delegate 增强**：并发委派（ThreadPoolExecutor，结果顺序归位）+ 超时控制（慢 Agent 降级不阻塞）+ 耗时统计
- **stats.py**：`CompanionStats` 协同统计（组合/耗时/成功率/并行比例/Top 组合）
- **细化映射**：专业 Agent 精确对接 Service 方法（参数白名单 + 回退）

### 3.11 V5.2 Perception & Strategy Integration 感知-战略集成

- **pipeline.py**：`AgentPipeline` 数据管道（前序输出 → 后序输入，顺序依赖，严格/宽松模式）
- **感知-策略闭环**：`perception → experience → planning`（环境状态 → 策略建议 → 规划输入）
- **delegate 增强**：管道感知委派（依赖顺序执行 + pipeline/pipeline_stages 输出）

### 3.12 V5.3 Execution & Feedback Loop 执行-反馈闭环

- **executor.py**：`ExecutionCoordinator`（execute → run_goal 经 Permission / feedback_loop / close_loop 闭环循环上限内 / audit）
- **闭环管道**：`perception → experience → planning → execution → feedback`
- **execution_agent**：第 7 专业 Agent（run_goal，权限拒绝不重试）

### 3.13 V5.4 Self-Correction & Learning 自我修正与学习

- **correction.py**：`SelfCorrector`（失败 → 规则调整 → 再执行，上限内）
  - 修正策略表 6 条：position_mismatch→先移动 / boundary_limit→缩短移动 / object_missing→先扫描 / object_not_held→先拾取 / invalid_parameter→修正参数 / permission_denied→不可修正
- **learning.py**：`CompanionLearning`（失败/成功模式统计 → 规则表，阈值提升）
  - LearningRule: {pattern, action, count, last_seen, reason}
- **修正审计**：CorrectionRecord: {attempt, reason, adjustment, result}

---

## 四、核心数据模型

### 4.1 基础数据（schema.py）

| 模型 | 关键字段 |
|---|---|
| `EmbodiedGoal` | goal_id/description/intent/target/scene/constraints/priority |
| `EmbodiedAction` | action_type/intent/target/parameters/risk_level/confidence/reason |
| `EnvironmentState` | objects/location/conditions/relations/confidence |
| `Feedback` | result/environment_change/error/latency_ms |
| `EnvironmentEvent` | event_type/cause/object_changes/summary |

### 4.2 策略与规划

| 模型 | 关键字段 |
|---|---|
| `ExperiencePolicy` | trigger/strategy/kind/scene/goal_type/version/status/hit_rate/family_id |
| `CrossGoalPlan` | plan_id/groups/shared_steps/budget_allocation/explainable_reason |
| `LongGoal` | goal_id/status(6)/milestones/dependencies/progress/priority |
| `Milestone` | milestone_id/order/status(5)/sub_goals/completion_rate |

### 4.3 伙伴架构

| 模型 | 关键字段 |
|---|---|
| `CompanionResponse` | request_id/intent/assigned_agents/results/aggregated/dispatched_parallel/total_latency_ms/pipeline/pipeline_stages |
| `ExecutionRecord` | goal/status/success/latency_ms/feedback/error/permission_required |
| `LearningRule` | pattern/count/last_seen/reason |
| `CorrectionRecord` | attempt/reason/adjustment/result |
| `PipelineStage` | stage/source/target/input_from/output_to/reason |

---

## 五、完整智能闭环（数据流）

```
┌─────────────────────────────────────────────────────────────┐
│                     YHLZ 完整智能闭环                        │
│                                                             │
│  外部目标 → MainCompanionAgent (统一人格/统一决策中心)        │
│      ↓ 路由 (加权打分 + Top-K)                              │
│  专业 Agent 分派                                             │
│      ↓                                                      │
│  感知 (perception) → 推理 (reasoning) → 经验 (experience)   │
│      ↓ 数据管道 (V5.2)                                      │
│  规划 (planning: 跨目标/预算)                                │
│      ↓                                                      │
│  长期任务 (long_horizon: 里程碑/进度)                        │
│      ↓ 执行管道 (V5.3)                                      │
│  执行 (execution → run_goal, 经 Permission)                 │
│      ↓ 反馈 (V5.3)                                          │
│  反馈分析 → 经验学习 (V4.3)                                  │
│      ↓ 修正 (V5.4)                                          │
│  失败 → 规则调整 → 再执行 (上限内)                           │
│      ↓ 学习 (V5.4)                                          │
│  失败/成功模式 → 规则表 (阈值提升)                           │
│      ↓                                                      │
│  治理 (V4.5: 冗余/冲突/回收站/进化/健康)                     │
│      ↓ 审计 (全链路可追溯)                                  │
│  统一响应 (CompanionResponse + 可解释原因)                   │
└─────────────────────────────────────────────────────────────┘
```

**数据流原则**：
- 规划只输出方案（不自动执行）
- 执行必须经 Permission Layer
- 治理只影响策略表/审计/快照
- 全程不写 Agent Memory（Embodied 独立环境记忆除外）
- 每一步输出可解释（explainable_reason）

---

## 六、安全约束体系

### 6.1 核心铁律

| 约束 | 落实 |
|---|---|
| 禁止 NN 训练/梯度/黑盒 | 全部为规则+统计+阈值+状态机 |
| 默认拒绝 | `embodied_enabled=False`，`companion_enabled=False` |
| 执行经 Permission | run_goal / execute_action 内部校验 |
| 不写 Agent Memory | Embodied 独立环境记忆，不触碰 Agent 子系统记忆 |
| 不控制真实设备 | 默认 Mock 环境，Hardware 需显式开启 |
| 不改 Agent Brain/Vision/Memory Interface | 只改 Embodied 模块 |
| 不自我生成目标 | 目标由外部提供 |

### 6.2 分层异常隔离

```
Adapter → 可抛异常（实现层）
Manager → 捕获转错误帧（不外抛）
Service → 捕获记录日志（返回结构化错误）
API    → 捕获返回 HTTP 错误码
```

### 6.3 线程安全

- 全部共享状态用 `threading.RLock` 保护
- 单例 + reset（`get_service/reset_service`）
- 线程池（companion 委派）显式 shutdown

---

## 七、配置驱动体系

全部配置进 `backend/config.py`，环境变量前缀加载：

| 前缀 | 版本 | 示例 |
|---|---|---|
| `embodied_*` | V4.0~4.7 | embodied_enabled / policy_min_hit_rate / mission_max_phases |
| `companion_*` | V5.0~5.4 | companion_enabled / route_topk / pipeline_strict / correction_max_attempts |

**禁止**：业务代码中的魔法数字 / 硬编码路径 / 写死阈值。

---

## 八、测试体系

### 8.1 测试命令

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

### 8.2 测试统计（V5.4）

| 子系统 | Total | Failed |
|---|---|---|
| embodied | 1815 | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **2551** | **0** |

### 8.3 测试分层

- 单元测试：每个子系统 `tests/` 目录
- 集成测试：跨模块端到端（governance_integration / v5x_integration）
- 治理专项（V4.5 起）：≥目标用例数（当前 1815 ≥ 1814）
- 全量回归：跨子系统 Failed=0

---

## 九、演进路径与未来方向

### 9.1 已完成进化

```
单体智能 (V4.0~V4.7)
    ↓
内部多智能体 (V5.0)
    ↓
协同增强 (V5.1)
    ↓
感知-策略闭环 (V5.2)
    ↓
执行-反馈闭环 (V5.3)
    ↓
自我修正与学习 (V5.4)
```

### 9.2 未来方向（V5.5+）

- **V5.5 Companion Adaptive Personality**：人格维度状态（热情/耐心/幽默/严肃）+ 情境适应（任务/结果 → 维度调整）+ 互动记忆（成功/失败 → 人格倾向）+ 人格审计
- 保持一个人格 / 一个核心意识 / 一个决策中心

### 9.3 最终愿景

让 YHLZ 持续成为：

```
有声音 / 有视觉 / 有记忆 / 有人格 / 能思考 / 能行动
持续进化的 AI 伙伴
```

**稳定开发 / 增量迭代 / 可测试 / 可维护 / 可扩展**

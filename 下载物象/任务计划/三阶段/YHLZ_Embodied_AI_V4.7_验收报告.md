# YHLZ Embodied AI V4.7 验收报告

> 版本：V4.7.0（Long Horizon Planning Layer 长期任务规划层）
> 日期：2026-08-07
> 项目根：`D:\YHLZ2.0`；工作区：`backend/embodied/`
> 前置：V4.6 已验收（embodied 1172 / 全量 1908, Failed=0）

---

## 一、完成状态

| 项目 | 状态 |
|---|---|
| V4.7 长期任务规划（Long Horizon Planning Layer） | ✅ 完成 |
| V4.7 专项测试 | ✅ 141 用例（专项合计 1313） |
| 全量回归（embodied） | ✅ 1313 tests, Failed=0 |
| 跨子系统回归（Vision/Action/Agent/Personality/voice_identity） | ✅ 全部 Failed=0 |
| 验收报告 | ✅ 本文档 |
| 下一阶段 Prompt | ✅ `YHLZ_Embodied_AI_V5.0_下一步开发Prompt.txt` |

**核心能力跃迁：** AI 跨目标统筹规划（V4.6）→ **AI 管理长期任务**（V4.7）。
从"我知道下一步做什么"升级为"我知道一个长期目标应该如何推进"，保持纯规则 + 状态机 + 统计 + 阈值 + 可解释，无任何 NN 训练 / 黑盒优化。

---

## 二、修改内容

### 2.1 规划包新增 5 个模块 `backend/embodied/planning/`

| 文件 | 内容 |
|---|---|
| `milestone.py` | `LongGoal` 数据模型（status: pending/active/paused/completed/failed/archived）+ `Milestone`（pending/running/completed/failed/blocked + 状态机校验）+ `MilestoneManager`（创建/分解/子目标/完成/回滚/进度查询） |
| `dependency_graph.py` | `DependencyGraph`：依赖设置（存在性 + 循环检测）/ 依赖图（前置/后续/阻塞原因）/ 阻塞计算 / 拓扑排序 |
| `progress_tracker.py` | `ProgressTracker`：get_progress / update_progress（100% 自动完成）/ progress_report（Goal 60% / Completed 3/5 / Blocked / Next）/ snapshot + restore_from_snapshot（按 order 跨会话恢复） |
| `adjustment.py` | `PlanAdjuster`：adjust_plan（4 种触发条件 → 新顺序/优先级建议，permission_required=True 禁止自动执行）/ predict_risk（历史失败 → low/medium/high）/ time_plan（deadline/duration/time_window） |
| `long_horizon.py` | `LongHorizonPlanner` 门面：create_long_goal / decompose_goal / generate_milestones（模板）/ track_progress / progress_report / complete/rollback_milestone / set_dependencies / pause/resume/fail/archive / adjust_plan / predict_risk / time_plan / snapshot / plan_milestone_goals（V4.6 集成）/ long_horizon_dry_run |

### 2.2 Service 新增 14 个 V4.7 API（V4.5/V4.6 API 全部不变）

| API | 功能 |
|---|---|
| `long_horizon_plan(title, phases)` | 创建 + 自动/手动分解主入口 |
| `long_horizon_decompose` | 手动分解（阶段 + 子目标） |
| `long_horizon_progress` / `long_horizon_report` | 进度跟踪 + 文本报告 |
| `long_horizon_milestone(goal_id, mid, complete/rollback)` | 里程碑管理 |
| `long_horizon_dependencies` | 依赖图（设置/查询） |
| `long_horizon_status(pause/resume/fail/archive)` | 状态管理 |
| `long_horizon_adjust` / `long_horizon_risk` / `long_horizon_time` | 调整/风险/时间 |
| `long_horizon_snapshot` | 快照（支持断点恢复） |
| `long_horizon_plan_milestones` | 里程碑 → V4.6 跨目标规划衔接 |
| `long_horizon_dry_run` / `long_horizon_list` | 预演 / 列表 |

### 2.3 其他修改
- `backend/embodied/strategy/audit.py`：AUDIT_ACTIONS 新增 7 个 V4.7 动作（create_long_goal / decompose_goal / milestone_complete / plan_adjust / goal_pause / goal_resume / goal_fail）
- `backend/config.py`：新增 6 项 `embodied_*` 配置（mission_max_phases / mission_retry_limit / mission_resume_enabled / risk_failure_threshold / risk_blocked_threshold / deadline_warning_hours）
- `backend/embodied/__init__.py`：`__version__ = "4.7.0"` + long_horizon 导出
- `backend/embodied/service.py` / `governance/__init__.py`：版本升 4.7.0

### 2.4 新增测试文件（4 个，141 用例）

| 文件 | 覆盖 | 用例数 |
|---|---|---|
| `tests/test_long_horizon_milestone.py` | LongGoal/Milestone 模型 + 状态机 + 分解/完成/回滚 | 33 |
| `tests/test_long_horizon_dependency_progress.py` | 依赖图/阻塞/拓扑 + 进度/报告/快照恢复 | 31 |
| `tests/test_long_horizon_adjustment.py` | 4 触发条件调整/风险预测/时间规划 | 31 |
| `tests/test_long_horizon_planner.py` | 门面 20 方法 + Service 14 API + 审计/安全/兼容/端到端 | 46 |

---

## 三、测试结果

### 3.1 Embodied 专项（验收命令）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 指标 | 数值 |
|---|---|
| Total | **1313**（≥1250 ✅） |
| Passed | 1313 |
| Failed | **0** ✅ |
| Skipped | 0 |

其中 V4.7 新增长期任务专项 141 用例全部通过。

### 3.2 全量回归（跨子系统）

| 子系统 | Total | Failed |
|---|---|---|
| embodied | 1313 | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **2049** | **0** ✅ |

---

## 四、V4.7 能力验收对照（v4.7.txt）

| 需求 | 实现 | 状态 |
|---|---|---|
| Long Goal 创建 | `create_long_goal`（pending 初始 + explainable_reason） | ✅ |
| Goal 分解 | `decompose_goal` → 完整任务树（里程碑 + 子目标） | ✅ |
| Milestone 管理 | `add/complete/rollback_milestone` + `query_progress` + 状态机校验 | ✅ |
| Dependency Graph | `dependency_graph`（前置/后续/阻塞原因/循环警告）+ `execution_order` 拓扑 | ✅ |
| Progress Tracking | `get_progress/update_progress/progress_report`（Goal 60% / Completed 3/5 / Blocked / Next） | ✅ |
| Plan Adjustment | `adjust_plan`（4 触发条件 → 新顺序/优先级/建议, permission_required=True 禁止自动执行） | ✅ |
| Dry Run | `long_horizon_dry_run`（拆解/时间估计/风险点/依赖关系 + 保护规则, 不落地） | ✅ |
| Audit | 7 个 V4.7 审计动作入白名单 + 全流程审计追踪 | ✅ |
| Snapshot | `snapshot`（状态/完成/阻塞/下一步）+ `restore_from_snapshot`（断点恢复） | ✅ |
| 与 V4.6 集成 | `plan_milestone_goals`（里程碑 → Cross Goal Planner → 子规划） | ✅ |
| Memory 集成 | 只读 Experience Memory（风险预测用失败历史）, 禁止修改（测试验证不写 Memory） | ✅ |
| 时间规划 (P1) | `time_plan`（deadline / estimated_duration / time_window / on_schedule/warning/overdue） | ✅ |
| 风险预测 (P1) | `predict_risk`（历史失败次数/阻塞 → low/medium/high + 可解释原因） | ✅ |
| 安全约束 | embodied_enabled=False 保持 / 不写 Agent Memory / 不绕过 Permission / 纯规则 | ✅ |
| 全量测试通过 | 专项 1313 + 全量 2049, Failed=0 | ✅ |

---

## 五、问题与风险

### 5.1 已解决问题（开发中发现并修复）
| 问题 | 修复 |
|---|---|
| Service.long_horizon_plan 自动分解后手动 decompose 重复被拒 | 自动模式直接返回模板任务树（generate_milestones 已分解） |
| 快照恢复按 milestone_id 匹配失败（跨会话 ID 不同） | 改为按 order 映射恢复状态 + 依赖关系重映射 |
| dry_run 临时目标未注册导致分解失败 | 预演用临时对象直接构建任务树（不落地） |
| 里程碑 pending → completed 被状态机拒绝 | 允许 pending 直接完成（任务可跳过） |

### 5.2 已知遗留（低风险）
| 问题 | 影响 | 处置 |
|---|---|---|
| `plan_milestone_goals` 需外部传 CrossGoalPlanner（Service 已自动注入） | 门面独立调用时子规划为空 | Service API 已封装, 门面用法文档化 |
| `generate_milestones` 模板仅识别部分中文关键词 | 未命中走默认 4 阶段 | 模板表可扩展（调整规则） |
| 进度按里程碑数均分（无权重） | 里程碑耗时差异未计入进度 | V5.0 可引入耗时权重 |

### 5.3 未来风险
- **状态机严谨性**：非法迁移抛异常（如 running → blocked），调用方需遵循标准流转；已在测试覆盖标准路径
- **快照跨会话恢复依赖 order 稳定性**：若新会话阶段顺序变化，恢复映射可能错位（当前按 order 映射保证同构恢复）

---

## 六、架构影响

| 维度 | 说明 |
|---|---|
| 影响模块 | 新建 `planning/milestone.py` `dependency_graph.py` `progress_tracker.py` `adjustment.py` `long_horizon.py`；修改 `service.py` `strategy/audit.py` `__init__.py` `config.py` |
| 兼容情况 | V4.5/V4.6 全部 API 签名不变；版本统一升 4.7.0 |
| 分层 | `LongHorizonPlanner` 经 Service 唯一接入；planning 只依赖 schema/policy/audit，不跨层 |
| 扩展能力 | 阶段模板 / 触发条件 / 风险阈值 / 时间警告阈值全部可配置；审计动作白名单可扩展 |
| 无侵入 | 未改 Agent Brain / Vision / Memory Interface；规划只输出方案不执行；允许读取 Memory 禁止写入 |

---

## 七、下一阶段建议

见 `YHLZ_Embodied_AI_V5.0_下一步开发Prompt.txt`（Adaptive Companion Architecture 自适应 AI 伙伴架构：Internal Multi-Agent System）。

V4.7 使 YHLZ 成为**最后一个单体智能阶段**（"长期 AI 伙伴"的基础）：
- 能"创建"长期目标（pending → active 生命周期）
- 能"拆解"（Long Goal → Milestone → Sub Goals → 任务树）
- 能"管理"（依赖 / 进度 / 调整 / 风险 / 时间 / 快照恢复）
- 能"追踪"（7 类长期任务审计）
- 能"预演"（不落地的 dry run + 保护规则）
- 全程可解释、可恢复、纯规则驱动

V5.0 将引入 Internal Multi-Agent System（Main Companion Agent + Specialist Agents），保持一个人格 / 一个核心意识 / 一个决策中心。

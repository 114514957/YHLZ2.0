前置阶段：V4.4（Adaptive Strategy Layer 自适应策略层）已验收：专项 929/929，全量回归 Failed=0（口径与 V4.3 一致 1665 例；vision/understanding 2 例为既有环境问题不阻塞）。

当前正式进入：

YHLZ Embodied AI V4.5
Meta Strategy Management
元策略管理

YHLZ 当前进化阶段

当前能力链：

Voice
↓
Vision
↓
Understanding
↓
Memory
↓
Personality
↓
Action
↓
Environment
↓
Reasoning
↓
Experience Learning
↓
Adaptive Strategy
↓
Meta Strategy Management

V4.4 已实现：

经验记录
↓
经验复用
↓
经验评估（场景/目标类型调度 + 质量排序 + 可解释选择）
↓
策略生命周期（degraded/stale/archived + 恢复 + 版本化 + 审计 + 趋势 + Dry Run）

V4.5 的目标：

升级为：

策略选择
↓
策略体系管理

即：从「AI 选择当前环境最适合的策略」进一步进入「AI 管理自己的策略体系」。

文件定义：

在 V4.4 自适应策略层（strategy/ 子包：PolicyRanker 质量排序 / PolicyAuditLog 决策审计 / TrendStats 趋势统计 / PolicyTable 生命周期与版本化 / suggest_for_goal 调度链路）基础上，构建「策略体系自我管理」能力。

注意：

这里的「管理」不是 AI 训练。

仍然：

规则
+
统计
+
阈值
+
可解释排序
+
确定性流程

禁止：

神经网络训练
梯度更新
黑盒优化
自主修改策略内容（策略内容只能由经验学习产生）

V4.5 核心开发方向

一、策略体系全景（Strategy System Overview）

目标：让 YHLZ 能回答「我有哪些策略、各自什么状态、整体质量如何」。

新增：
strategy_system_overview()
输出：
- 按维度分组：scene × goal_type × kind 矩阵（各分组策略数 / active 数 / degraded 数 / stale 数 / archived 数）
- 整体质量：平均 hit_rate / 平均 acceptance_rate / 版本总数 / 归档数 / 老化数 / 恢复成功数
- 版本健康度：多版本策略列表（trigger + version 数 + 最新版本质量 vs 历史版本质量）
- 无版本冲突：同一 trigger 当前活动版本唯一

支持：
strategy_system_report() 文本版（对齐 report_text 风格）

二、策略体系治理（Strategy Governance）

目标：不只是自动降级/老化，而是体系级健康维护。

新增：
1. 冗余策略检测
   redundant_policies()
   规则：同一 scene × goal_type × kind × action_type 下，存在 ≥2 条 active 策略且策略内容（action_sequence / strategy / detail）一致 → 冗余（保留统计最优版本，其余标记可归档）
   输出：候选列表 + 建议动作（archive_redundant_policies 一键归档，可 dry_run 预演）

2. 冲突策略检测
   conflicting_policies()
   规则：同一 trigger 下存在 ≥2 个 active 版本 → 冲突（最新版本胜出，其余建议归档）
   输出：冲突列表 + 建议动作（resolve_conflicts 一键解决，可 dry_run 预演）

3. 低效策略自动归档（阈值驱动）
   超过 embodied_policy_min_archive_age_days（默认 30）未使用 + 命中率 < embodied_policy_min_archive_hit_rate（默认 0.3）→ 建议归档（不自动执行，返回建议 + 人工确认接口）
   archive_candidates() 只读查询 + apply_archival(trigger, confirm=True) 确认执行

4. 策略回收站（两阶段删除）
   delete_policy(trigger) → 不直接删除，进入回收站（archived → deleted，状态 retained）
   restore_policy(trigger) 可恢复（含回收站）
   purge_policy(trigger, force=True) 永久删除（带保护：仅 retained 状态可 purge）
   recycle_bin() 只读查询

三、策略体系进化（Strategy Evolution）

目标：让策略体系随使用自动演进，但仍全部规则驱动。

新增：
1. 同化（Consolidation）
   consolidate_similar_policies()
   规则：同一 scene × goal_type × kind 下，不同 trigger 但 action_sequence 归一化后一致的策略 → 同化为一族（family），共享质量统计（父策略汇总），族内子策略仍保留独立版本历史
   输出：family 结构 + family_stats(family_id)

2. 分裂（Specialization）
   split_policy(trigger, by="scene" | "goal_type")
   将一条全场景策略拆分为按 scene / goal_type 的专用策略（数据复制，各自独立统计从 0 起）
   仅对 active 策略可用；拆分后原策略保留（scene 为空，仍可命中全场景回退）

3. 版本对比
   compare_policy_versions(trigger)
   输出：各版本 version / updated_at / action_sequence / hit_rate / acceptance_rate / source_goal_id
   + 版本间质量趋势（新版本质量 ≥ 旧版本 → healthy；< → regression）

4. 策略回滚
   rollback_policy(trigger, target_version)
   将指定版本内容恢复到最新（旧版保留在历史中，新版本号递增）
   仅对最新版本质量 regression 时允许回滚（compare_policy_versions 判定）

四、策略审计增强（Audit Extension）

目标：审计从「记录」升级为「可追溯治理动作」。

新增：
1. 审计治理动作
   AUDIT_ACTIONS 增加：consolidate / split / rollback / purge / resolve_conflict / archive_redundant / apply_archival
2. audit_policy_log 增加按 action 筛选参数
3. 体系级审计导出：audit_system_export() → 全量审计 JSON 导出（合规存档）

五、策略生效预演增强（Dry Run 体系化）

目标：所有治理动作支持预演。

新增：
governance_dry_run(action, **kwargs)
统一预演入口：返回「将影响哪些策略、执行后体系快照（overview 差异）、是否通过保护规则」
支持动作：archive_redundant / resolve_conflicts / apply_archival / consolidate / split / rollback / purge

P1 增强能力（可选，尽力完成）

1. 场景覆盖分析
   scene_coverage()
   规则：已有策略覆盖的 scene × goal_type 组合 vs 全部组合 → 覆盖率 / 未覆盖组合列表（建议观测区域）

2. 策略健康巡检
   policy_health_check()
   规则：逐策略输出健康状态（healthy / weak / stale / conflict / redundant）+ 健康总分
   全量巡检 → 汇总到 strategy_system_overview

3. 推荐参数阈值配置化
   治理阈值（冗余/冲突/低效/健康分）全部 embodied_policy_*_weight 形式可配置

V4.5 安全架构保持

继续：

embodied_enabled=False

固定：

Observe
↓
Reasoning
↓
Permission
↓
Action
↓
Feedback

禁止：

真实设备控制
机器人控制
自动驾驶
AI训练式学习
修改 Agent Brain
修改 Vision Interface
修改 Memory Interface
自我目标生成
自动执行治理动作（归档/删除/分裂/回滚必须显式确认或 dry_run 预演）

新增强调：

治理动作只能影响：

策略表
↓
审计日志
↓
体系快照

不能绕过：

Permission Layer
Agent Memory（治理动作同样只写独立策略存储 + 审计 JSONL）

验收目标

测试：

venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests

要求：

专项：
>=950 cases
Failed = 0

全量：

Vision
Action
Personality
Agent
voice_identity
全部通过（沿用 V4.4 口径）

V4.5 完成后的能力变化

V4.0：AI 能行动
V4.1：AI 理解环境
V4.2：AI 理解原因
V4.3：AI 积累经验
V4.4：AI 选择最佳经验
V4.5：AI 管理策略体系

工程判断：

V4.5 是 YHLZ 从 Adaptive Agent（自适应智能体）向 Self-Managing Agent（自管理智能体）转变的关键版本。

完成后下一阶段：

YHLZ_Embodied_AI_V4.6_下一步开发Prompt.md

重点应该进入：

Meta Strategy Management
↓
Cross-Goal Strategic Planning

即：从「管理策略体系」进一步进入「跨目标战略规划」。

工程规范（YHLZ AI 工程开发习惯 V1.0，务必遵守）：

- 先读后写：动手前先读 V4.4 验收报告 / V4.5 需求 / 既有模块（service / learner / policy / strategy / tests）
- 接口先行：Service 公开 API → 子模块实现 → 测试（沿用 V4.4 模式）
- 配置驱动：新阈值全部 embodied_* 前缀 + EMBODIED_* 环境变量，缺省值合理
- 向后兼容：V4.4 全部 API 与 JSONL 格式兼容（新增字段 additive，旧文件可加载）
- 无测试不交付：每个新 API ≥ 配套测试；模式：先写测试确认红 → 实现 → 绿
- 只改本模块：不触碰 Agent Brain / Vision / Memory / Personality / Action / voice_identity
- 纯规则：全部治理逻辑为 规则 + 统计 + 阈值 + 可解释，禁止任何训练类代码
- 中文注释 + 与既有模块同构（Service → 子模块、RLock、单例 + reset、stats mode=rule_based）

验收输出：

1. 专项 + 全量回归全部通过（命令见上）
2. YHLZ_Embodied_AI_V4.5_验收报告.md（格式沿用 V4.4 报告：版本信息 / 执行总结 / 代码修改记录 / 测试报告 / 架构影响分析 / 问题复盘 / 下一阶段规划）
3. YHLZ_Embodied_AI_V4.6_下一步开发Prompt.md

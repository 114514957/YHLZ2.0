# YHLZ 会话交接文档（V6.5）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.6 Autonomous Growth Maturation**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.6_下一步开发Prompt.txt`
- 方向：反思-情绪集成（`reflection/reflection_emotion.py`，经 Meaning）+
  成长闭环自动化（`growth/growth_cycle.py`，应用仍审批）+
  成长趋势入报告
- 专项目标 ≥5160（当前 4760 + 400），Failed=0

---

## 1. V6.5 已实现（本会话）

### 1.1 认知反思层 `reflection/`（新增 4 文件，与 V5.8 同目录不同名）

| 文件 | 内容 |
|---|---|
| `cognitive_reflection.py` | CognitiveReflectionEngine：analyze(records, identity) → {summary, pattern, success_factor, failure_factor, confidence, patterns, contradictions} |
| `pattern_analyzer.py` | PatternAnalyzer：min_samples(≥2)/min_streak(≥2)/min_success_rate；连续成功→success_strategy，连续失败→problem_pattern，重复→repetition；按置信度排序+上限 |
| `contradiction_detector.py` | CognitiveContradictionDetector：identity_conflict（中文字段名：使命/价值观/人格/安全规则/权限）/knowledge_conflict（同触发器相反结果）/value_conflict（不+可靠/诚信/安全/尊重/负责） |
| `reflection_report.py` | ReflectionReport：Reflection Memory {experience_id, reflection, pattern, growth_value} |

### 1.2 自主成长层 `growth/`（新增 4 文件）

| 文件 | 内容 |
|---|---|
| `growth_proposal.py` | GrowthProposal：4 类型（skill_improvement/memory_strategy/interaction_strategy/reasoning_strategy），上限截断 |
| `growth_evaluator.py` | GrowthEvaluator：三检查 identity（中文字段名+英文）/safety（敏感词）/value（风险→分数）；**value ok 是硬约束**（高风险拒绝）；score=3 维均值 |
| `growth_applier.py` | GrowthApplier：**默认需人工确认**（change_fn 缺失 → pending_confirm）；guard_fn 二次确认；变更验证不可变字段 |
| `growth_audit.py` | GrowthAudit：{before, proposal, decision, after, time}，可关 |

### 1.3 身份保护层 `identity/`（新目录）

`identity_guard.py`（PROTECTED_FIELDS: mission/core_value/base_personality/safety_rules/permission，拦截记录）·
`change_validator.py`（Before/Change/Reason/After/Verification，保护字段拒绝）

### 1.4 集成

- Service API 9 个：`companion_reflection_analyze/pattern_detect/contradiction_check` +
  `companion_growth_generate/evaluate/apply/audit/stats`
- config 5 项新（pattern_analysis/growth_proposal/growth_auto_apply=false/identity_guard/growth_audit）；
  `reflection_enabled` 复用 V6.4（**config 只有一个**，勿重复定义）
- 快照 12 域（+reflection_state + growth_state）
- main_agent 构造：cognitive_reflection/growth_engine(dict: proposal/evaluator/applier)/identity_guard(dict: guard/validator)

---

## 2. 测试现状（V6.5 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **4760**（V6.5 新增 405, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **5496** | **0** |

V6.5 新增测试 8 个：`test_v650_pattern(29)` / `test_v650_reflection_core(34)` /
`test_v650_growth(56)` / `test_v650_integration(31)` / `test_v650_extra(50)` /
`test_v650_extra2(44)` / `test_v650_extra3(111,生成式)` / `test_v650_extra4(50,生成式)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 生成式测试模式（V6.5 引入）

`test_v650_extra3/4.py` 用 `setattr(Class, name, func)` 生成批量测试方法
（def test(self) 闭包 + __name__ 重命名）。unittest 正常加载（测试计数含生成方法）。
静态 `def test_` 统计会漏计生成方法，用 discover 计数（见 count_v650_tests.py）。

### 3.2 受控应用语义（重要）

- `GrowthApplier.apply`：`evaluation.approved=False` → blocked；
  `approved=True` 但无 change_fn 且 `_auto_apply=False` → **pending_confirm**（默认需人工确认）
- main_agent.growth_apply：evaluation 为空时自动评估；changes 传入即 change_fn；
  Identity Guard 前置检查（保护字段 → blocked）
- `growth_auto_apply` 配置默认 false（**硬保持**）

### 3.3 评估硬约束

`GrowthEvaluator`：identity 检查失败 → 直接拒（score 0）；
safety/value ok 也是硬约束（approved 需要三者 ok + score ≥ 0.6）。
value 分数：risk low=0.9/medium=0.6/high=0.3（+0.05 若有收益）。

### 3.4 矛盾检测中文匹配

identity_conflict 用中文字段名（使命/价值观/人格/安全规则/权限）或英文 field 名；
value_conflict 用"不+可靠/诚信/安全/尊重/负责"模式。
**新增检测关键词时保持中文可解释。**

### 3.5 快照 12 域

identity/personality/relationship/experience/verification/reflection/
creative/creative_memory/emotion/perception_stats/reflection_state/growth_state。

### 3.6 版本号

6.5.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` /
`storage/snapshot/restore/identity_snapshot` / 全部测试断言。

### 3.7 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`patch_v650_*.py` / `fix_v650_version.py` /
`smoke_v650.py` / `demo_v650.py` / `count_v650_tests.py` / `count_v650_total.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 反思不联动情绪 | 认知与情绪分离 | V6.6 reflection_emotion |
| 成长闭环人工触发 | 未自动化 | V6.6 growth_cycle |
| 成长趋势不入报告 | 缺趋势分析 | V6.6 growth_trend |
| identity_conflict 关键词匹配 | 语义弱 | V6.6/7 增强 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 / 反思≠意识

---

## 6. 下一阶段

V6.6 Autonomous Growth Maturation：
反思-情绪集成 + 成长闭环自动化 + 成长趋势。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.6_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.5_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

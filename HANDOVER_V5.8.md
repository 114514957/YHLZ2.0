# YHLZ 会话交接文档（V5.8）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-07

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V5.9 Creative Proposal Engine（主动发现/建议/创新，初步元创造力）**

- 任务文件：`下载物象\任务计划\三阶段\` 下的 V5.9 Prompt（若未生成需参考 v5.8.txt 第 23 节方向自建）
- 方向：从被动响应进入主动建议（发现问题 → 提出方案 → 等待确认）
- 前置模块（已就绪）：ReflectionEngine 输出（模式/失败/建议）+ ImprovementProposalEngine（审批流）
- 目标：专项 ≥2515（当前 2315 + 200），Failed=0

**注意**：V5.8 尚未持久化 Proposal/Reflection（内存态），V5.9 可优先补持久化。

---

## 1. 项目背景与版本演进

YHLZ = 元·亨·利·贞（《周易》），长期成长型 AI 伙伴系统。

已完成版本（全部 Failed=0）：

| 版本 | 名称 | 能力 |
|---|---|---|
| V4.0 | Environment Foundation | AI 能行动 |
| V4.1 | Environment Intelligence | AI 理解环境 |
| V4.2 | Environment Reasoning | AI 理解原因 |
| V4.3 | Experience Learning | AI 积累经验 |
| V4.4 | Adaptive Strategy | AI 选择最佳经验 |
| V4.5 | Meta Strategy Management | AI 管理策略体系 |
| V4.6 | Cross-Goal Planning | AI 跨目标统筹规划 |
| V4.7 | Long Horizon Planning | AI 管理长期任务 |
| V5.0 | Adaptive Companion Architecture | 内部多智能体协作 |
| V5.1 | Companion Coordination | 并发/超时/加权路由/统计 |
| V5.2 | Perception & Strategy Integration | Agent 数据管道 |
| V5.3 | Execution & Feedback Loop | 执行协调器/反馈闭环 |
| V5.4 | Self-Correction & Learning | 自我修正/学习器 |
| V5.5 | Identity & Adaptive Personality | 人格维度/情境适应 |
| V5.6 | Relationship & Personality Stability | 关系状态/人格衰减/窗口 |
| V5.7 | Experience Memory | 经历记录/抽取/查询/反思 |
| V5.8 | Reflection & Cognitive Integrity | 反思引擎/经验验证/认知免疫 |

核心哲学：**纯规则 + 统计 + 阈值 + 可解释 + 确定性流程**（禁止 NN 训练/黑盒/自我修改核心人格）。

---

## 2. 测试现状（V5.8 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **2315** | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **3051** | **0** |

（voice_identity 无 `__init__.py`，需显式模块运行；tts 无 tests。）

---

## 3. V5.8 已实现（本会话）

### 3.1 反思层 `companion/reflection/`

| 文件 | 内容 |
|---|---|
| `reflection_engine.py` | ReflectionEngine：经历 → Reflection Report（observation/evidence/pattern/risk/suggestion/confidence）+ reflect_with_verification（只 CONFIRMED）+ stats |
| `pattern_discovery.py` | PatternDiscovery：跨经历模式（4 条件：样本≥3/跨度≥1天/重复/反例≤0），禁止单次事件形成规则 |
| `failure_analysis.py` | FailureAnalysisEngine：原因 5 分类（execution/strategy/permission/environment/unknown）+ 证据 + 置信度 + 修正建议 |
| `improvement_proposal.py` | ImprovementProposalEngine：Proposal ≠ Action，PENDING_APPROVAL → APPROVED → EXECUTED |
| `reflection_audit.py` | ReflectionAudit：9 动作追踪 |

### 3.2 认知完整性层 `companion/verification/`

| 文件 | 内容 |
|---|---|
| `experience_verifier.py` | 验证状态机 UNKNOWN→PENDING→PROBABLE→CONFIRMED/REJECTED（阈值 2/2，REJECTED 可新证据回 PENDING） |
| `confidence_engine.py` | 5 因素加权（source 0.3/occurrence 0.2/consistency 0.2/contradiction 0.2/stability 0.1）+ 分级 + suggest_status |
| `evidence_manager.py` | 证据（来源事件/时间/结果/证据） |
| `contradiction_detector.py` | 对立词检测 → Context-dependent 场景化合并（不覆盖） |
| `reality_check.py` | 5 问验证（来源/证据/重复/反例/价值）→ 影响行为建议 |

### 3.3 Service API（V5.8 新增）

`companion_reflection()` / `companion_reflection_validated()` / `companion_verification_stats()` / `companion_verification_confirm(id)` / `companion_verification_reject(id)` / `companion_proposal_stats()`

配置：`companion_verification_confirm_threshold` / `reject_threshold` / `companion_pattern_min_occurrences`

### 3.4 handle 联动

`handle` 每次委派后：记录经历（V5.7）→ 验证经历（V5.8，evidence=1）→ 关系更新 → 人格调整 → 附 personality/relationship/window_stats。

---

## 4. 关键事实清单（供新会话直接使用）

### 4.1 Service property 命名约定（重要教训）

**禁止 property 与 API 方法同名**（方法后定义会遮蔽 property）。历史修复：
- `companion_personality`（方法）→ property 用 `companion_personality_engine`
- `companion_relationship`（方法）→ property 用 `companion_relationship_manager`
- `companion_reflection`（方法）→ property 用 `companion_reflection_engine`
- `companion_verifier`（property 无同名方法，安全）

新 property 一律用 `companion_xxx_engine/manager` 风格。

### 4.2 加载顺序（load_config）

load_config 中：先 `self._companion_config = dict(config)` + 重置全部 `_companion_*` 字段 → 再构造 MainCompanionAgent（依赖各 property 懒加载）。**不要在构造后重置字段**（会清空刚创建的实例，导致 agent 与 API 持有不同实例）。

### 4.3 版本号位置

`backend/embodied/__init__.py`（__version__）/ `service.py`（4 处）/ `governance/__init__.py` / `companion/main_agent.py` status + 全部测试断言。用 Python 脚本批量替换（禁止 PowerShell 写中文文件——GBK 编码事故教训）。

### 4.4 测试文件（V5.8 新增 5 个，200 用例）

`test_verifier.py` / `test_confidence.py` / `test_reflection.py` / `test_reflection_engine.py` / `test_v58_integration.py`

### 4.5 临时脚本

`C:\Users\lenovo\AppData\Local\Temp\opencode\`（已预授权）：`fix_v58*.py` 等修复脚本、冒烟输出。

---

## 5. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| Proposal/Reflection 内存态（无持久化） | 重启丢失 | V5.9 优先补 JSONL 持久化 |
| 模式发现依赖时间戳跨度 | 单会话多次同 trigger 不形成模式 | 符合设计限制（防止单次事件成规则） |
| 失败原因关键词规则 | 复杂错误归 unknown | 可解释兜底 |
| 经历/关系/人格状态内存态 | 跨进程不连续 | V6.x 持久化 |

---

## 6. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：embodied_enabled=False 默认 / 执行经 Permission / 不写 Agent Memory / 不控真实设备

---

## 7. 下一阶段

V5.9 Creative Proposal Engine：主动发现问题 → 提出方案 → 生成创新建议（Proposal 持久化 + 审批）。方向见 v5.8.txt 第 23 节与完成报告。

**YHLZ · 元 · 亨 · 利 · 贞**

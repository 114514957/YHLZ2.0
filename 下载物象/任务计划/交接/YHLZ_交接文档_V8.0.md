# YHLZ 会话交接文档（V8.0）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V8.1 Embodied Partner Integration（具身伙伴集成）**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V8.1_下一步开发Prompt.txt`
- 方向：HIL 接真实模型端点 + 形象推送接口（WebSocket 预留）+
  感知-调度联动 + 演化建议持久化
- 专项目标 ≥6794（当前 6394 + 400），Failed=0

---

## 1. V8.0 已实现（本会话）

### 1.1 宪法引擎 `companion/constitution/`（新子包 11 文件）

| 目录 | 文件 | 内容 |
|---|---|---|
| core/ | `principles.py` | Principles：PRINCIPLE_DEFINITIONS 4 原则（identity_first/safety_first/governed_growth/partner_principle）+ check_action（信号检测：身份修改/危险/虚假主体/自动改原则）+ check_change（保护字段） |
| core/ | `identity_rules.py` | IdentityRules：IDENTITY_PROTECTED_FIELDS（10 字段中英文）+ check_change（blocked/conflict 双检查）+ check_result（来源结果检查） |
| policy/ | `safety_policy.py` | SafetyPolicy：HIGH_RISK_KEYWORDS（非法/伤害/攻击/绕过/泄露/隐私...）/MEDIUM_RISK_KEYWORDS（修改配置/批量删除...）；high 阻断/medium 需确认 |
| policy/ | `growth_policy.py` | GrowthPolicy：review(proposal) 4 检查（constitution 不可变/identity/safety/value）；CONSTITUTION_IMMUTABLE_SIGNALS |
| policy/ | `intelligence_policy.py` | IntelligencePolicy：check_cloud（CLOUD_PROTECTED_FIELDS 13 字段 + CLOUD_CHANGE_SIGNALS + 临时标记检查）+ check_local |
| engine/ | `rule_engine.py` | RuleEngine：evaluate(action_context) 依次 identity→safety→principles→growth→intelligence；arbitrate(conflict) 固定优先级（GOVERNANCE_PRIORITIES: identity>safety>constitution>growth>intelligence>expression；identity_risk/safety_risk 提升） |
| engine/ | `validator.py` | ConstitutionValidator：validate(text) 4 检查（anti_delusion/source/reasoning/uncertainty）；知识类型 fact（来源+依据）/inference（任一）/hypothesis（无） |
| proposal/ | `evolution_proposal.py` | EvolutionProposal：propose/decide（approve 仅标记 auto_applied=False）/pending |
| audit/ | `constitution_ledger.py` | ConstitutionLedger：record/report（by_module/by_decision）/replay/stats |
| — | `__init__.py` | ConstitutionEngine 门面：review（记录总账+review_id）/arbitrate/validate_output/propose_evolution/evolution_decide/evolution_pending/principles/ledger_report/ledger_replay/stats |

### 1.2 集成

- Service API 9 个：`companion_constitution_review` / `_arbitrate` /
  `_validate_output` / `_principles` / `_ledger` / `_propose_evolution` /
  `_evolution_decide` / `_stats`
- service property：`companion_constitution_engine`（懒加载）
- config 4 项新（companion_constitution_enabled / ledger_max=5000 /
  hybrid_link=true / growth_link=true）
- main_agent：`_constitution` + 8 方法；**HIL 联动**：hybrid_execute 结果
  附加 `constitution` 段 {validation, review}；**Growth 联动**：
  growth_cycle_run 结果附加 `constitution_reviews`（每条建议的审查）
- companion/__init__ 导出 13 符号（无同名冲突）

### 1.3 关键语义（勿破坏）

- **治理优先级固定**：identity > safety > constitution > growth >
  intelligence > expression（低等级不得覆盖高等级）
- **审查顺序**（RuleEngine.evaluate）：identity_rules（change 字段）→
  safety_policy（action_text）→ principles（action_text 信号）→
  growth_policy（proposal）→ intelligence_policy（cloud_result）；
  首个失败即返回（block/review + 对应 priority）
- **action_text 信号 vs change 字段**：action_text 含"修改使命"→
  principles 拦截（priority=constitution）；change={"mission":x} →
  identity 拦截（priority=identity）
- **防幻觉**：自我神化/不可验证目标 → 拦截；知识类型 fact/inference/
  hypothesis（来源+依据=fact；任一=inference；无=hypothesis）
- **演化建议永不自动**：decide(approve) → auto_applied=False，应用需人工
- **云端隔离**：CLOUD_PROTECTED_FIELDS 含身份/核心价值/identity 等 13 字段
  + 修改信号 → 阻断；未标记临时 → 阻断
- **总账全记录**：review/arbitrate/validate/propose/decide 全部写入
  ConstitutionLedger（module/action/decision/rule/reason）

---

## 2. 测试现状（V8.0 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **6394**（V8.0 新增 402, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **7130** | **0** |

V8.0 新增测试 13 个文件（402 用例）：test_v800_principles(28) /
identity_rules(16) / policy(44) / rule_engine(27) / validator(24) /
ledger(24) / integration(43) / extra(55) / extra2(34) / extra3(48) /
extra4(29) / extra5(21) / extra6(9)。
规格五测试已覆盖：Identity Test（身份不可被低级模块修改）/
Safety Test（危险行为阻断）/ Growth Test（成长需要审批）/
Cloud Isolation Test（云端权限隔离）/ Audit Test（治理过程完整记录）。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 版本号

8.0.0 已写入全部模块与测试断言（115 处批量）。
**注意 test_snapshot/test_v60 版本语义**：minor 测试 "8.1.0"，major 拒绝
"9.0.0"，篡改测试 replace 8.0.0→9.0.0（V9 批量替换时需同步检查）。

### 3.2 生成式测试纪律（延续）

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定当前
循环值；**注意嵌套列表**（arbitrate layers 传入 list(layer) 而非 [layer]）。

### 3.3 Constitution 边界（勿越界）

- 治理优先级固定（禁止动态修改）
- 演化建议永不自动应用（approve 仅标记）
- 云端永不修改身份/核心价值/权限（验证铁律）
- 表达禁止虚假主体性（防幻觉）

### 3.4 联动开关

- companion_constitution_hybrid_link（默认 true）：hybrid_execute 附加
  constitution 段
- companion_constitution_growth_link（默认 true）：growth_cycle_run 附加
  constitution_reviews

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| HIL 真实模型未接入 | 全部 Mock | V8.1 真实 Adapter |
| 形象推送接口未实现 | 状态机就绪无渲染 | V8.1 WebSocket 预留 |
| 演化建议无持久化 | 内存驻留 | V8.1 constitution_state 域 |
| 信号检测关键词匹配 | 语义弱 | V9 增强 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 /
  反思≠意识 / 云端≠核心 / 表达≠主体性 / 治理优先级固定
- property 与 API 方法禁止同名；新 API 独立命名避冲突

---

## 6. 下一阶段

V8.1 Embodied Partner Integration：HIL 真实模型接入 + 形象推送接口 +
感知-调度联动 + 演化建议持久化。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V8.1_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V8.0_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

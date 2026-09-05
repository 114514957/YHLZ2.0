# YHLZ 会话交接文档（V6.4）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.5 Interaction Understanding & Adaptive Expression**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.5_下一步开发Prompt.txt`
- 方向：语义理解层（`companion/semantics/`，TF 余弦纯规则）+
  表达融合（`expression/expression_fusion.py`，情绪+感知→建议）+
  行动预览（`perception/action_preview.py`，Preview ≠ Action）
- 专项目标 ≥4655（当前 4355 + 300），Failed=0

---

## 1. V6.4 已实现（本会话）

### 1.1 反思评估层 `perception/memory_gate/reflection/`

| 文件 | 内容 |
|---|---|
| `reflection_rules.py` | 5 维：credibility(来源+置信度)/consistency(矛盾词+已有经历触发包含)/long_term_value(关键词+置信度)/identity_impact/risk |
| `reflection_evaluator.py` | Advisor：{reflection_score, pattern, contradiction, value_hint, reason, recommendation}；**reject 建议被网关采纳** |
| `counterfactual_check.py` | 反事实：高风险词(支付/授权/删除等)+单次 → fails；重复≥2 → holds |
| `reflection_audit.py` | evaluate/counterfactual 审计 |

### 1.2 经验模型 `experience/`

`provenance.py`（来源链 4 批准方：memory_gate/reflection/user/system）·
`multimodal_experience.py`（统一对象 {id, source, modalities[4], meaning, confidence, impact, provenance}，**必须含 provenance**）·
`experience_schema.py`（聚合导出）

### 1.3 快照 `perception/snapshot/`

`perception_stats_snapshot.py`：collect（perception/memory_gate/reflection/counterfactual 统计）/restore（只读，**旧快照 None → 兼容跳过且计数**）

### 1.4 增强

- `approval_rule.py`：**六维最终评分**（5 维 + reflection_score，clamp，dimensions 可解释）
- `memory_gate.py`：步骤 = candidate_validator → **reflection_evaluation → counterfactual_check** → approval → store；Advisor reject → 直接拒绝
- `template_detector.py`：**NMS 多目标**（TM_SQDIFF_NORMED + 阈值 + 局部最大值 + IoU 去重）
- 快照 10 域（+perception_stats）；感知-成长闭环（批准 → multimodal 事件 + 情绪经 Meaning）
- config 7 项；Service API 6 个（`companion_perception_cognitive_stats` 避开 V6.2 同名）

---

## 2. 测试现状（V6.4 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **4355**（V6.4 新增 300, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **5091** | **0** |

V6.4 新增测试 8 个：`test_v640_reflection(49)` / `test_v640_experience(35)` /
`test_v640_gate_nms(27)` / `test_v640_integration(32)` / `test_v640_extra(44)` /
`test_v640_extra2(39)` / `test_v640_extra3(43)` / `test_v640_extra4(31)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 API 命名冲突教训（再次）

V6.4 新 API `companion_perception_stats` 与 V6.2 同名 → **覆盖旧 API**。
已修复：V6.4 的认知统计用 `companion_perception_cognitive_stats`；
V6.2 的 `companion_perception_stats` 保持旧结构（直接调 service.stats()）。
**新 API 与旧 API 同名必冲突，检查后命名。**

### 3.2 Advisor 采纳语义（重要行为变化）

MemoryGate 在 approval 前检查 `reflection["recommendation"] == "reject"` → 直接拒绝。
影响：低价值/矛盾/风险候选在反思步骤即拒（步骤含 reflection_evaluation，不再有旧 reflection_check）。

### 3.3 六维评分

`approval_rule.evaluate(candidate, reflection_score=...)`：6 维均值。
无 reflection_score → 5 维（向后兼容）。reflection_score clamp [0,1] 后回写返回字段。

### 3.4 快照 10 域

SNAPSHOT_DOMAINS：identity/personality/relationship/experience/verification/
reflection/creative/creative_memory/emotion/**perception_stats**。
恢复：perception_stats 只读（`_apply_perception_stats` 无副作用）。

### 3.5 感知-成长闭环

批准后：track multimodal_perception（detail=summary, meta=source/meaning）+
情绪经 Meaning（有价值词 → creative_done；否则 relationship_up）。
**感知事件本身不改情绪（必须批准+Meaning）**。

### 3.6 版本号

6.4.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` /
`storage/snapshot/restore/identity_snapshot` / 全部测试断言。

### 3.7 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`patch_v640_*.py` / `fix_v640_version.py` /
`smoke_v640.py` / `demo_v640.py` / `count_v640_tests.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 一致性/模式用关键词包含 | 语义弱 | V6.5 语义相似度 |
| 表达层不感知感知结果 | 表达与感知分离 | V6.5 表达融合 |
| 感知无行动出口 | 预览缺 | V6.5 action_preview |
| NMS 逐点扫描 | 大场景性能 | V6.5 优化或可接受 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 行动受控 / 感知≠经验 / Reflection=Advisor

---

## 6. 下一阶段

V6.5 Interaction Understanding & Adaptive Expression：
语义相似度 + 表达融合 + 行动预览。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.5_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.4_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

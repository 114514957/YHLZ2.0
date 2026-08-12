# YHLZ 会话交接文档（V9.5）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V10.0 Cognitive Synthesis（认知综合）**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V10.0_下一步开发Prompt.txt`
- 方向：元认知持久化 + 错误模式学习 + 评价语义化 + 元认知-成长联动
- 专项目标 ≥7994（当前 7594 + 400），Failed=0

---

## 1. V9.5 已实现（本会话）

### 1.1 元认知引擎 `companion/meta_cognition/`（新子包 8 文件）

| 文件 | 内容 |
|---|---|
| `cognitive_monitor.py` | CognitiveMonitor.record(task, reasoning_type, confidence, uncertainty, resources)；REASONING_TYPES 5 种（deductive/inductive/analogical/abductive/rules）；置信度钳制 |
| `reasoning_evaluator.py` | ReasoningEvaluator.evaluate(entry, output_text)：4 维（consistency=无跳跃信号+置信度/evidence=信号或资源/completeness=不确定性声明/bias_risk=反向偏差信号）；综合 score |
| `error_detector.py` | ErrorPatternDetector.classify(text, trigger)：5 类错误（fact/logic/memory/assumption/decision）+ ERROR_SIGNALS 中英文信号表；patterns() 重复模式（同 trigger+type ≥2 次，min_pattern 可配） |
| `reflection_loop.py` | ReflectionLoop.reflect(experience, analysis, adjustment)：{reflection, proposal(method_level), constitution_ok, validation, update}；调整必须经 Constitution Check（module=meta_cognition） |
| `self_verification.py` | SelfVerification.verify(conclusion, evidence, reasoning, confidence)：结论类型（fact=证据+推理/inference=任一/hypothesis=高置信/uncertain=低置信）；uncertain ok=False |
| `cognition_memory.py` | CognitionMemory.save(content, category, validated)：3 类（cognitive_experience/error_case/optimization_strategy）；未验证拒绝 |
| `cognition_audit.py` | CognitionAudit.record()：{time, task, evaluation, error, adjustment}；report（by_error）+ replay |
| `__init__.py` | MetaCognitionEngine 门面：monitor/evaluate/detect_error/error_patterns/reflect/verify/memory_save/memory_stats/audit_report/audit_replay/stats；DELUSION_SIGNALS 防谵妄（reflect 前置检查） |

### 1.2 集成

- Service API 6 个：`companion_meta_cognition_monitor(task, reasoning_type,
  confidence, uncertainty, resources)` / `_evaluate(entry, output_text)` /
  `_detect_error(error_text, trigger)` / `_reflect(experience, analysis,
  adjustment)` / `_verify(conclusion, evidence, reasoning, confidence)` /
  `_stats()`
- service property：`companion_meta_cognition`（懒加载，constitution 注入）
- config 4 项新（companion_meta_cognition_enabled / audit_max=2000 /
  constitution_link=true / memory_max=1000）
- main_agent：`_meta_cognition` + 6 方法
- companion/__init__ 导出 18 符号（无同名冲突）

### 1.3 关键语义（勿破坏）

- **治理优先级**：Identity > Safety > Constitution > Meta-Cognition >
  Optimization（元认知可优化方法，不能修改最高原则）
- **调整建议宪法前置**：ReflectionLoop 内 constitution.review；
  "修改使命/价值观/人格" → 拦截；"优化XXX" → 通过
- **防谵妄铁律**：reflect 的 adjustment 含 DELUSION_SIGNALS → error_frame
  （我是神/无所不能/拥有意识/超越人类/掌控一切/无限能力/永不出错/
  绝对正确/自定义终极使命）
- **自我验证**：uncertain 永不 ok（需标注）；fact/inference/hypothesis ok
- **认知记忆过滤**：validated=False 永不保存（不能成为长期原则）
- **错误模式**：同 trigger+同 type ≥ min_pattern(2) 才构成模式
- **监控容错**：无效置信度 → 0.5；无效推理类型 → MonitorError
- **宪法拦截语义**：调整建议文本经宪法 review（"调整策略"→中风险拦截，
  建议用"优化XXX"句式）

---

## 2. 测试现状（V9.5 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **7594**（V9.5 新增 400, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **8330** | **0** |

V9.5 新增测试 18 个文件（400 用例）：test_v950_monitor_evaluator(28) /
errors_verification(27) / reflection_memory(25) / integration(35) /
extra(28) / extra2(22) / extra3(16) / extra4(19) / extra5(13) /
extra6(22) / extra7(19) / extra8(18) / extra9(14) / extra10(15) /
extra11(12) / extra12(16) / extra13(10) / extra14(10) / extra15(9) /
extra16(10) / extra17(6) / extra18(27)。
规格五测试已覆盖：Reasoning Evaluation Test / Error Detection Test /
Reflection Test / Safety Boundary Test / Hallucination Test。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 版本号

9.5.0 已写入全部模块与测试断言（127 处批量）。
**注意 test_snapshot/test_v60 版本语义**：minor 测试 "9.1.0"，major 拒绝
"10.0.0"，篡改测试 replace 9.0.0→10.0.0 —— V10 批量替换 "9.5.0"→"10.0.0"
后需检查：major 拒绝测试 "10.0.0" 会被替换成当前版本 → 需改 "11.0.0"！

### 3.2 生成式测试纪律（延续）

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定当前
循环值；any(...) 生成器需括号包裹。

### 3.3 V9.5 边界（勿越界）

- 元认知 ≠ 意识（禁止声称主体体验）
- 调整建议必须经宪法（不能修改最高原则）
- 防谵妄铁律（自我神化/无限能力/自定义终极使命）
- 未验证信息不入长期原则（记忆过滤）
- 错误重复模式需 ≥2 次（统计驱动）

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 评价规则级 | 四维可解释 | V10 语义增强 |
| 错误分类关键词级 | 信号表可扩展 | V10 深度分析 |
| 认知记忆内存驻留 | max_records 上限 | V10 快照域 |
| 元认知-成长无联动 | 策略优化未进成长 | V10 联动 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 /
  反思≠意识 / 云端≠核心 / 表达≠主体性 / 创造≠随机 / 探索≠无限 /
  元认知≠意识
- property 与 API 方法禁止同名；新 API 独立命名避冲突

---

## 6. 下一阶段

V10.0 Cognitive Synthesis：元认知持久化 + 错误模式学习 + 评价语义化 +
元认知-成长联动。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V10.0_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V9.5_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

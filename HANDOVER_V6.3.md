# YHLZ 会话交接文档（V6.3）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.4 Perception-Memory Deep Integration**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.4_下一步开发Prompt.txt`
- 方向：感知-反思深度评估（`perception/memory_gate/reflection_evaluator.py`）+
  感知统计快照持久化（SNAPSHOT_DOMAINS + perception_stats 域）+
  感知-成长闭环（批准 → multimodal 事件 + 情绪联动）+
  多目标模板检测（NMS 规则）
- 专项目标 ≥4355（当前 4055 + 300），Failed=0

---

## 1. V6.3 已实现（本会话）

### 1.1 真实感知引擎 `perception/adapters/`

| 文件 | 内容 |
|---|---|
| `tesseract_ocr.py` | TesseractOCRAdapter：pytesseract + get_tesseract_version 验证；无环境 → is_available=False → skipIf |
| `template_detector.py` | TemplateDetectorAdapter：**TM_SQDIFF_NORMED**（cv2 5.0 的 CCOEFF 全 1.0 异常，改用 SQDIFF）；confidence = 1 - min_val |

### 1.2 记忆网关 `perception/memory_gate/`

`approval_rule.py`（5 维：source_trust/repetition/long_term_value/identity_impact/risk；
**风险 ≥0.5（1 词）直接拒绝**；评分 = 均值，≥0.6 批准）·
`candidate_validator.py`（必填 5 字段/来源白名单/摘要 ≤200）·
`memory_gate.py`（校验 → 反思回调 → 批准 → store_fn 写入，source=vision_perception）

### 1.3 感知管道 `perception/pipeline/`

`perception_frame.py`（{type, content, verified, meaning, timestamp}）·
`perception_router.py`（vision/ocr→perception_agent，text→reasoning_agent，audio→audio_agent；
**未验证帧 + object 敏感类型 → action_allowed=False**）·
`agent_pipeline_adapter.py`（ingest → agent_input 观察上下文，无行动指令）

### 1.4 集成

- Service API 4 个：`companion_perception_memory_gate(_stats)` +
  `companion_perception_frame` + `companion_perception_pipeline_stats`
- config 9 项（`perception_real_enabled` / `tesseract_enabled` /
  `template_detection_enabled` / `memory_gate_enabled` /
  `pipeline_perception_enabled` / `camera_access_enabled` /
  `memory_gate_approve_threshold` / `memory_gate_reject_threshold` /
  `perception_template_match_threshold`）

---

## 2. 测试现状（V6.3 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **4055**（V6.3 新增 301, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **4791** | **0** |

V6.3 新增测试 8 个：`test_v630_adapters(24)` / `test_v630_memory_gate(52)` /
`test_v630_pipeline(36)` / `test_v630_integration(31)` / `test_v630_extra(44)` /
`test_v630_extra2(39)` / `test_v630_extra3(32)` / `test_v630_extra4(43)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 模板匹配实现要点（重要教训）

cv2 5.0.0 + numpy 2.4.6 环境下 `TM_CCOEFF_NORMED` **全部返回 1.0**（环境 bug）。
已改用 `TM_SQDIFF_NORMED`（min 匹配，confidence = 1 - min_val），4 类场景验证正确。
**V6.4 多目标 NMS 必须基于 SQDIFF 继续。**

### 3.2 批准评分语义

- 综合评分 = 5 维均值（0~1）；≥0.6 approved / <0.3 rejected / 中间 rejected（"未达批准阈值"）
- 风险维度 ≥0.5（1 个风险关键词：删除/覆盖/格式化/关闭/危险/密码/支付/授权）→ 直接拒绝
- 候选 source 保留实际来源（V6.3 修复 V6.2 固定 "vision" 的缺陷）

### 3.3 安全链路（保持）

```
receive → verify (Schema→Source→Confidence≥0.5) → 候选
→ memory_gate.process (validator → reflect_fn → approval → store)
→ 经历 (source=vision_perception)
```

- 未验证帧 / object 敏感帧 → action_allowed=False（管道）
- 感知不直接写记忆（必须批准）、不触碰人格、帧无行动指令

### 3.4 Tesseract 环境

本机**无 pytesseract** → is_available=False → 2 个测试 skipIf。
安装 `pip install pytesseract` + tesseract 可执行后自动启用（无需改代码）。

### 3.5 版本号

6.3.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` /
`storage/snapshot/restore/identity_snapshot` / 全部测试断言。

### 3.6 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`fix_v630_version.py` /
`patch_v630_*.py` / `smoke_v630.py` / `demo_v630.py` / `count_v630_tests.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 反思检查是占位回调 | 未深度评估 | V6.4 reflection_evaluator |
| 感知统计不持久化 | 重启丢失 | V6.4 快照 perception_stats 域 |
| 感知未联动成长/情绪 | 多模态闭环未闭合 | V6.4 批准 → track + 情绪 |
| 模板匹配单次单目标 | 多实例漏检 | V6.4 NMS 规则版 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 行动受控 / 多模态隔离

---

## 6. 下一阶段

V6.4 Perception-Memory Deep Integration：
反思评估器 + 感知统计快照 + 感知-成长闭环 + 多目标检测。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.4_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.3_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

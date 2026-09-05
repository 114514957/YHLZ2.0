# YHLZ 会话交接文档（V6.2）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.3 Embodied Perception & Action Integration**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.3_下一步开发Prompt.txt`
- 方向：真实感知引擎（Tesseract OCR + 模板匹配，Mock 同接口 skipIf）+
  感知-反思-记忆批准流程（`perception/memory_gate.py`）+
  Agent Pipeline 感知帧输入
- 专项目标 ≥4054（当前 3754 + 300），Failed=0

---

## 1. V6.2 已实现（本会话）

### 1.1 表达层 `companion/expression/`

| 文件 | 内容 |
|---|---|
| `expression_rules.py` | 5 条规则（高积极/低能量/高温度/高信任/任务失败）；**字段存在才判断**（空上下文中性） |
| `expression_context.py` | 上下文聚合（Emotion/Relationship/Task/Conversation） |
| `expression_engine.py` | generate → {style, tone, reason, confidence, timestamp} + 统计/审计 |
| `expression_audit.py` | generate/status 审计 |

### 1.2 感知层 `companion/perception/`

| 文件 | 内容 |
|---|---|
| `schema.py` | PerceptionEvent/OCRResult/DetectionResult + 校验（_content_raw 防非 dict） |
| `interface.py` | PerceptionAdapter 抽象基类 |
| `manager.py` | 注册/路由/异常隔离（错误帧） |
| `service.py` | 权限→适配器→验证→记忆候选（不直接进 Memory） |
| `permission.py` | 四层开关默认拒绝（perception/vision/ocr/detection） |
| `verification.py` | Schema→Source→Confidence→Approved |
| `audit.py` | 8 动作，可关（perception_audit_enabled） |
| `adapters/` | vision_mock / ocr_mock / detection_mock / camera_adapter |

### 1.3 集成

- Service API 11 个：`companion_expression_generate/status/audit` +
  `companion_vision_ocr/detect` + `companion_perception_receive/verify/audit/stats/memory_candidates`
- growth_meaning 新增 `multimodal_perception` 事件
- config 11 项：`companion_expression_enabled/threshold` +
  `perception_enabled/vision_enabled/ocr_enabled/detection_enabled/permission_required/audit_enabled/min_confidence/default_ocr/default_detection`

---

## 2. 测试现状（V6.2 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **3754**（V6.2 新增 300） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **4490** | **0** |

V6.2 新增测试 9 个：`test_expression(44)` / `test_perception_basic(56)` /
`test_perception_service(42)` / `test_v620_integration(33)` /
`test_v620_extra(48)` / `test_v620_extra2(59)` / `test_v620_extra3(18)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 命名冲突教训（延续）

`expression_audit.AuditError` / `perception.audit.AuditError` 与
`experience_audit.AuditError` 顶层同名——**均不导出到 companion 顶层**
（经子包访问）。新模块导出前检查冲突。

### 3.2 感知安全管道（重要语义）

```
receive (事件) → verify (Schema→Source→Confidence) → APPROVED
→ memory_candidate (PENDING_REFLECTION, 不直接写经历)
```

- 低可信（conf < min_confidence 0.5）→ REJECTED，不产生候选
- 候选 promote 是显式操作（V6.3 用 memory_gate 反思批准）
- 感知不注入 handle 响应

### 3.3 权限语义

- `perception_enabled`（总开关）+ 3 子开关；全默认 False
- 未授权 → 短路返回 PERMISSION_DENIED（不调用 Adapter）
- 冒烟/演示需要显式开启全部

### 3.4 表达语义

- 空上下文 → neutral/neutral (conf 0.3)
- 规则按字段存在性判断（emotion 缺 energy 不触发 low_energy）
- 组合时 hits[0] 为主风格（规则顺序：高积极 > 低能量 > 高温度 > 高信任 > 任务失败）

### 3.5 版本号

6.2.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` /
`storage/snapshot/restore/identity_snapshot` / 全部测试断言。

### 3.6 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`fix_v620_version.py` /
`smoke_v620.py` / `demo_v620.py` / `count_v620_tests.py` / `patch_v620_*.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 真实 OCR/检测引擎未接入 | Mock 占位 | V6.3 Tesseract/模板匹配 |
| 记忆候选无批准流程 | promote 为显式操作 | V6.3 memory_gate 反思批准 |
| 感知未接入 Agent Pipeline | 感知无出口 | V6.3 pipeline 扩展 |
| 摄像头依赖 OpenCV | 无环境不可用 | skipIf 保护 |
| 感知统计未持久化 | 重启丢失 | V6.3 快照扩展 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 感知≠理解 / 表达≠人格修改 / 多模态隔离

---

## 6. 下一阶段

V6.3 Embodied Perception & Action Integration：
真实感知引擎（Tesseract/模板匹配）+ 记忆批准流程 + Agent Pipeline 感知输入。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.3_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.2_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

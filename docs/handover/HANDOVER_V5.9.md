# YHLZ 会话交接文档（V5.9）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.0 Long-term Growth Companion（长期成长闭环）**

- 任务文件：`下载物象\任务计划\三阶段\YHLZ_V6.0_下一步开发Prompt.txt`
- 方向：全量持久化（经历/验证/关系/人格/反思/创造方案统一 JSONL）+
  经验生命周期（活跃/冷/归档/回收）+ 成长报告（growth_tracker/report）
- 专项目标 ≥3038（当前 2788 + 250），Failed=0

**注意**：V5.9 仅方案记忆（ProposalMemory）支持 JSONL 持久化且默认关闭
（`companion_creative_memory_path` 空），其余状态仍内存态——V6.0 补全量持久化。

---

## 1. V5.9 已实现（本会话）

### 1.1 创造层 `companion/creative/`

| 文件 | 内容 |
|---|---|
| `opportunity_detector.py` | 5 类机会（repetition/failure/pattern/improvement/relationship），只基于 CONFIRMED 经验，含证据+置信度 |
| `value_evaluator.py` | 5 维评估（Impact 0.25/Frequency 0.2/Benefit 0.2/Feasibility 0.2/Risk 0.15 权重），决策 create(≥0.6)/defer(≥0.35)/reject |
| `creative_reasoning_engine.py` | 路径推理（来源映射+关键词补充，5 种路径），主路径置信度更高 |
| `proposal_generator.py` | 方案生成（标题规则按路径类型），只接受 decision=create |
| `simulation_engine.py` | 模拟（成功率≥0.7 proceed / ≥0.4 revise / else abandon，风险惩罚，副作用关键词检测） |
| `proposal_memory.py` | 状态机 PENDING→APPROVED/REJECTED→EXECUTED→COMPLETED/FAILED，JSONL 持久化（save_to_file/load_from_file） |
| `creative_audit.py` | 10 动作追踪（detect/evaluate/reason/propose/simulate/approve/reject/execute/result/persist） |
| `creative_engine.py` | 门面：run()（不执行）/detect/evaluate/reason/propose/simulate/approve/reject/execute/record_result（形成新经验）/persist/load/protections |

### 1.2 集成层 `companion/integration/`

| 文件 | 内容 |
|---|---|
| `experience_bridge.py` | 只 CONFIRMED 经验供给（无验证器→保守空）；record_new_experience + verify 回写闭环 |
| `reflection_bridge.py` | 读取 ReflectionEngine 最新报告；无引擎→空报告 |
| `approval_bridge.py` | 审批门槛（恒 True）；submit 在 V5.8 ImprovementProposalEngine 注册镜像 |

### 1.3 Service API（V5.9 新增 11 个）

`companion_creative_run/detect/evaluate/propose/simulate/approve/reject/execute/record_result/stats/audit`
配置：`companion_creative_*` 共 15 项（config.py）。

### 1.4 handle 联动

V5.9 未改 handle 主流程；creative 为独立主动层，经 Service API 触发。

---

## 2. 测试现状（V5.9 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **2788**（V5.9 新增 473） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **3524** | **0** |

V5.9 新增测试 10 个：`test_opportunity_detector.py(62)` / `test_value_evaluator.py(56)` /
`test_creative_reasoning.py(47)` / `test_proposal_generator.py(44)` /
`test_simulation.py(48)` / `test_proposal_memory.py(65)` / `test_creative_audit.py(33)` /
`test_creative_bridges.py(40)` / `test_creative_engine.py(62)` / `test_v59_integration.py(32)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 验证状态机（V5.8，V5.9 依赖）

`verify()` 一次 → UNKNOWN→PENDING；二次 → PROBABLE；三次 → CONFIRMED
（confirm_threshold=2 时）。测试造 CONFIRMED 经验需 **3 次 verify**。

### 3.2 创造闭环触发

`companion_creative_run()` = detect → evaluate(只 create 继续) → reason → propose → simulate，
**不执行**（auto_executed=False）。执行需 approve → execute → record_result。

### 3.3 record_result 闭环

`record_result(pid, success, result)` 自动调用 experience_bridge
`record_new_experience`（engineering 类型）+ `verify_new_experience`（证据 1，PENDING）。

### 3.4 关系字段名

`RelationshipManager.relationship()` 用 **`trust_level`**；CreativeEngine._relationship()
已做兼容映射（`trust = trust_level`），关系类机会可正常触发（已验证）。

### 3.5 Service property 命名（延续教训）

新 property 一律 `companion_xxx_engine/manager` 风格：`companion_creative_engine` ✓

### 3.6 load_config 顺序

`self._companion_config = dict(config)` + 重置全部 `_companion_*`（含新 `_companion_creative`）
→ 再构造 MainCompanionAgent（传 `creative_engine=self.companion_creative_engine`）。

### 3.7 版本号

5.9.0 已写入：`embodied/__init__.py` / `service.py`(4处+status) / `governance/__init__.py` /
`main_agent.py` status / `creative_engine.status()` / 全部测试断言（脚本批量）。

### 3.8 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`fix_v59_version.py` / `fix_v59_crlf.py` /
`fix_v59_testver.py` / `smoke_v59.py` / `demo_v59.py` / `count_v59_tests.py` 等。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 方案记忆持久化默认关闭 | 重启丢失创造方案 | V6.0 全量持久化 |
| 经历/验证/关系/人格/反思内存态 | 跨进程不连续 | V6.0 统一 JSONL |
| 机会检测依赖 CONFIRMED 量 | 冷启动创造能力有限 | 随经验积累增强 |
| 模拟成功率保守（规则） | 无黑盒（符合铁律） | 可接受 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：执行经 Permission / 不写 Agent Memory / 不控真实设备 / 纯规则

---

## 6. 下一阶段

V6.0 Long-term Growth Companion：全量持久化 + 经验生命周期 + 成长报告。
任务文件：`下载物象\任务计划\三阶段\YHLZ_V6.0_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\三阶段\YHLZ_V5.9_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

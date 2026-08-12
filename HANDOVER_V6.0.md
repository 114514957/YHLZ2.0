# YHLZ 会话交接文档（V6.0）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.1 Emotion Representation & Autonomous Growth Rhythm**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.1_下一步开发Prompt.txt`
- 方向：情绪表达层（`companion/emotion/`，3 维可计算状态，纯规则）+
  自主成长节律（`companion/rhythm/`，handle 联动采集 + 自动整理/快照触发器）
- 专项目标 ≥3450（当前 3200 + 250），Failed=0
- 注意：V6.0 快照域需扩展 emotion 域（RestoreManager 按域遍历已天然兼容）

---

## 1. V6.0 已实现（本会话）

### 1.1 持久化层 `companion/persistence/`

| 文件 | 内容 |
|---|---|
| `storage.py` | JSONLStorage：原子写（.tmp+os.replace）/校验（schema_version/type/timestamp/data）/损坏行跳过 |
| `snapshot.py` | CompanionSnapshot：8 域快照 + sha256 checksum（确定性 sort_keys 序列化） |
| `restore.py` | RestoreManager：Load→Checksum→Schema(主版本)→Identity(指纹)→Memory→Activate；失败跳过不崩溃 |
| `persistence_audit.py` | PersistenceAudit：10 动作 |

### 1.2 记忆体系 `companion/memory/`

`memory_importance.py`（四维评分：Identity/Relationship/Creative/Repeat，≥0.7 保护）
`memory_index.py`（5 类型索引）· `memory_consolidation.py`（Active→Cold→Archive→Recycle，
受保护强制归档，回收出索引）

### 1.3 身份历史 `companion/identity_history/`

`identity_snapshot.py`（快照+审批流；**不可变字段** mission/core_value/base_personality）
`identity_diff.py`（字段级差异，NOISE_FIELDS 忽略）· `identity_audit.py`

### 1.4 成长层 `companion/growth/`

`growth_meaning.py`（8 事件意义模板）· `growth_tracker.py`（事件+指标）
`growth_trend.py`（day/week/month 桶+delta+compare）· `growth_report.py`（四维报告）

### 1.5 门面 `continuity_engine.py`

save/load（失败不崩溃）/consolidate/capture_identity/propose-approve-reject
identity_change/growth_report/trend/metrics/stats/audit/protections(6 项)

### 1.6 Service API（新增 15 个）

`companion_persistence_save/load` · `companion_growth_report` ·
`companion_experience_lifecycle` · `companion_memory_overview` ·
`companion_identity_*`(5) · `companion_growth_trend/metrics` ·
`companion_continuity_stats/audit`
配置：`companion_persistence_*`(4) / `companion_memory_*`(1) / `companion_experience_*`(3) /
`companion_identity_*`(1) / `companion_growth_*`(3)，共 12 项。

---

## 2. 测试现状（V6.0 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **3200**（V6.0 新增 409） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **3936** | **0** |

V6.0 新增测试 10 个：`test_storage(38)` / `test_snapshot(50)` /
`test_persistence_audit(11)` / `test_memory_importance(35)` /
`test_memory_index(31)` / `test_memory_consolidation(39)` /
`test_identity_history(48)` / `test_growth(54)` /
`test_continuity_engine(53)` / `test_v60_integration(41)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 恢复应用器（appliers）

`_build_appliers()` 返回 6 域应用器：personality（base 校验一致才恢复维度）/
relationship（直接写 _state 字段）/ experience（store.clear + from_dict 重建 + 索引同步）/
verification（VerificationState 重建）/ reflection（_reports 替换）/ creative（memory 重建）。
**identity 域无应用器**（校验域，指纹一致性检查）。

### 3.2 enabled 语义（重要）

`companion_persistence_enabled` 控制 **save/load**（停用时抛 ContinuityError）；
`consolidate` / `identity` / `growth` **始终可用**（不触碰文件系统）。

### 3.3 身份指纹

`_compute_fingerprint()` = sha256({base_personality})；人格 base 不同 →
指纹不同 → RestoreManager 身份校验拒绝恢复（`test_identity_verify_mismatch_blocks`）。

### 3.4 快照篡改检测

快照篡改（state 修改）→ checksum 不匹配 → 恢复失败不崩溃。测试用正则替换
checksum 为全零（`test_tampered_checksum_denied`）。

### 3.5 V5.9 遗留（未改动）

creative 的 ProposalMemory JSONL 路径独立（`companion_creative_memory_path`）；
统一快照已覆盖其内存态。

### 3.6 版本号

6.0.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative/creative_engine.py` / `continuity_engine.status()` / 全部测试断言。

### 3.7 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`fix_v60_version.py` / `fix_v60_crlf.py` /
`patch_v60_enabled.py` / `smoke_v60.py` / `demo_v60.py` / `count_v60_tests.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 记忆整理/成长采集需显式触发 | 不自动 | V6.1 rhythm 触发器 |
| handle 不联动成长事件 | 成长报告缺 handle 数据 | V6.1 handle 联动 |
| 快照无 emotion 域 | V6.1 增加 | RestoreManager 按域遍历已兼容 |
| 人格维度恢复但不自动应用 | 审批仅记录决策 | 符合"变化必须提出"原则 |
| 双持久化路径（creative 独立 + 统一快照） | 并存不冲突 | 可后续统一 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：纯规则 / 执行经 Permission / 不写 Agent Memory / 身份不可变

---

## 6. 下一阶段

V6.1 Emotion Representation & Autonomous Growth Rhythm。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.1_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.0_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

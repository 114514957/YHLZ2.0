# YHLZ 会话交接文档（V6.1.1）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-08

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V6.2 Interaction Expression & Vision Perception**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.2_下一步开发Prompt.txt`
- 方向：表达层（`companion/expression/`，情绪→表达建议，仅建议不强制）+
  视觉感知子系统（`backend/vision_perception/`，OCR + 目标检测，Mock 优先，权限默认拒绝）
- 专项目标：embodied ≥3574（3454+120）+ vision_perception 新子系统 ≥150，Failed=0

---

## 1. V6.1.1 已实现（本会话）

### 1.1 情绪表征层 `companion/emotion/`

| 文件 | 内容 |
|---|---|
| `emotion_state.py` | EmotionState：positivity/energy/warmth [0,1] + floor 下限保护（默认 0.1）+ 基线（0.6/0.5/0.6） |
| `emotion_rules.py` | 8 情境规则表（success/failure/consecutive_fail/creative_done/creative_rejected/relationship_up/relationship_down/idle），`rule_for()` |
| `emotion_decay.py` | Current = Previous + Event Impact - Natural Decay；rate×gap×time_factor（window_days=7） |
| `emotion_engine.py` | update/decay/get_state/get_stats + 稳定性（连续 ≥3 次幅度×0.5）+ floor 防无限下降 |
| `emotion_memory.py` | 历史 {event, before, after, reason, impact} |
| `emotion_audit.py` | update/decay/reset/restore |

### 1.2 成长节律层 `companion/rhythm/`

| 文件 | 内容 |
|---|---|
| `growth_rhythm.py` | on_handle 联动：track（experience_added/task_completed）+ 情绪联动 + 自动整理/快照/反思 |
| `growth_trigger.py` | 条件：经验数阈值（默认 20）/ 整理天数（默认 7） |
| `consolidation_scheduler.py` | tick(experience_count, consolidate_fn) |
| `rhythm_audit.py` | capture/consolidate/snapshot/reflection/skip/error |

### 1.3 集成

- 快照扩展 emotion 域（SNAPSHOT_DOMAINS 9 域；旧快照无 emotion → 跳过兼容）
- growth_meaning 增加 `task_completed` 事件类型
- Service API 8 个：`companion_emotion(_adjust/_decay/_audit/_history)` +
  `companion_growth_rhythm(_cycle)` + `companion_rhythm_audit`
- main_agent handle 联动：response["rhythm"] 附节律结果
- 配置 11 项：`companion_emotion_enabled/decay_rate/update_step/decay_window_days/consecutive_limit/floor` +
  `companion_rhythm_enabled/consolidate_threshold/consolidate_days/daily_snapshot/auto_reflection`

---

## 2. 测试现状（V6.1.1 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **3454**（V6.1.1 新增 254） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **4190** | **0** |

V6.1.1 新增测试 7 个：`test_emotion_state(28)` / `test_emotion_decay(26)` /
`test_emotion_engine(43)` / `test_rhythm(36)` / `test_v611_integration(44)` /
`test_v611_extra(41)` / `test_v611_memory_extra(36)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 命名冲突教训（重要）

`companion/__init__.py` 顶层导出中，emotion 的 `rule_for` / `DecayError` /
`MemoryError` / `AuditError` 与 personality_rules / personality_decay /
proposal_memory / experience_audit **同名冲突**（后导入覆盖前导入）。
已修复：emotion 冲突名**不导出到 companion 顶层**（经 `companion.emotion` 子包访问）。
**新模块导出时务必检查顶层同名冲突。**

### 3.2 情绪稳定性规则

- 连续 failure/success ≥ consecutive_limit（默认 3）后，步长 ×0.5
- floor（默认 0.1）防止无限下降：30 次失败后 positivity = 0.1
- 衰减收敛需多次调用（每次移动 rate×gap×time_factor）

### 3.3 节律触发语义

- `ConsolidationScheduler` 首次 tick：last_run=0 → 天数条件（999 天）必触发
- 快照：`companion_rhythm_daily_snapshot` 且已配置 `companion_persistence_path` 才执行
- 反思：每天至多一次（`_last_reflect`）

### 3.4 快照 emotion 域

- collect_states 含 emotion（engine.get_state()）
- 恢复：`_apply_emotion` → engine.restore_state（last_reason=快照恢复）
- 旧快照无 emotion 域 → RestoreManager 按域遍历自动跳过（不报错）

### 3.5 版本号

6.1.1 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` /
`storage/snapshot/restore/identity_snapshot` 默认版本 / 全部测试断言。

### 3.6 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：`fix_v611_*.py` / `patch_v611_*.py` /
`smoke_v611.py` / `demo_v611.py` / `count_v611_tests.py`。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 情绪未修饰表达 | 情绪无出口 | V6.2 expression 层 |
| 视觉只有采集无理解 | 感知能力缺 | V6.2 vision_perception 子系统 |
| 情绪趋势不在成长报告 | 报告缺情绪维度 | V6.2 扩展 |
| 情绪未参与对话 | 仅状态表达 | V6.2 建议接口（不强制） |
| vision_perception 与 embodied 并行 | 独立子系统 | 按 vision 惯例（backend/vision/） |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 纯规则 / 身份不可变

---

## 6. 下一阶段

V6.2 Interaction Expression & Vision Perception：
表达层（情绪→建议）+ 视觉感知子系统（OCR/检测）。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V6.2_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.1.1_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

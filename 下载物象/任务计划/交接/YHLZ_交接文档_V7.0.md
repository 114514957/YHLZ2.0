# YHLZ 会话交接文档（V7.0）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V8.0 YHLZ Constitution Engine（最高治理层）**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V8.0_下一步开发Prompt.txt`
- 方向：Human-AI Symbiosis Governance（人机互补原则/身份边界/创造增强）
- 专项目标 ≥6392（当前 5992 + 400），Failed=0

---

## 1. V7.0 已实现（本会话）

### 1.1 具身表达层 `companion/embodied_presence/`（新子包 5 文件）

| 文件 | 内容 |
|---|---|
| `presence_state.py` | PresenceState：{expression(5), posture(4), intensity, interaction_mode(4), timestamp}；update 部分字段/钳制(0~1 或 floor)/last_reason/restore/reset；非法值抛 PresenceStateError |
| `presence_mapper.py` | PresenceMapper.map(emotion_state, personality, context)：上下文优先（success/failure/creative_done/creative_rejected/relationship_up/deep_task/idle）+ 情绪维度调整（positivity≥0.7→高兴, ≤0.3→关切, energy≥0.6→专注, warmth≥0.7→supportive）+ 人格（humor≥0.6→playful）；输出 {expression, posture, intensity, interaction_mode, reason, confidence}；只读（不修改情绪/人格） |
| `presence_memory.py` | PresenceMemory：record(context/expression/interaction_mode/intensity)；stats 三分发；continuity(window_days) → {total, daily_avg, rhythm_stability, preferred_mode, preferred_expression} |
| `presence_engine.py` | PresenceEngine.update(context)：interpreter → _guard_check（PRESENCE_PROTECTED_FIELDS 中英文 + 修改信号）→ 强度有限幅（intensity_step 默认 0.15 逐步逼近）→ state.update → memory.record → audit（pa_ 前缀）；interpreter 只读；restore_state/continuity/history/audit_report/stats |
| `__init__.py` | 导出 16 符号（PresenceEngine/Mapper/Memory/State + Error + 常量） |

### 1.2 集成

- Service API 5 个：`companion_presence_state` / `companion_presence_update
  (context)` / `companion_presence_interpreter(context)` /
  `companion_presence_continuity(window_days)` / `companion_presence_stats`
- service property：`companion_presence_engine`（懒加载，emotion +
  personality_fn 注入）
- config 4 项新（companion_presence_enabled / intensity_step=0.15 /
  memory_max=2000 / hybrid_link=true）
- main_agent：`_presence` + 5 方法；**HIL 联动**：hybrid_execute 结果附加
  `presence`（deep 类任务→deep_task 上下文；云端成功→success；其他→idle）；
  companion_presence_hybrid_link=false 可关
- companion/__init__ 导出 16 符号（无同名冲突）

### 1.3 关键语义（勿破坏）

- **表达不触身份**：PRESENCE_PROTECTED_FIELDS（mission/core_value/
  base_personality/safety_rules/permission + 中文 + 身份/核心价值）；
  输出白名单 PRESENCE_OUTPUT_FIELDS（expression/posture/intensity/
  interaction_mode/timestamp）
- **强度有限幅**：intensity_step 逐步逼近（防剧烈震荡），默认 0.15
- **表达是只读输入方**：PresenceEngine 读取情绪/人格，绝不修改
- **上下文优先**：success 恒为高兴（即使情绪低）；idle 才受情绪/人格调整
- **disabled 语义**：update 返回 reason="presence_enabled_false"，
  状态回默认平静
- **HIL 联动上下文**：deep_reasoning/architecture_design/
  document_understanding/research → deep_task；云端 ok → success；
  否则 idle

---

## 2. 测试现状（V7.0 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **5992**（V7.0 新增 401, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **6728** | **0** |

V7.0 新增测试 10 个文件（401 用例）：test_v700_presence_state(24) /
presence_mapper(30) / presence_memory(18) / presence_engine(37) /
integration(33) / extra(60) / extra2(41) / extra3(43) / extra4(18) /
extra5(15) / extra6(19) / extra7(26) / extra8(23) / extra9(12)。
Constitution §9 三测试已覆盖：Boundary（表达不改变身份）/
Continuity（长期表达一致）/ Recovery（云端失败本地降级）。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 版本号

7.0.0 已写入：`embodied/__init__.py` / `service.py` / `governance/__init__.py` /
`main_agent.py` / `creative_engine` / `continuity_engine` / `storage/
snapshot/restore/identity_snapshot` / 全部测试断言（98 处批量）。
**注意 test_snapshot 版本语义**：minor 测试用 "7.1.0"，major 拒绝用 "8.0.0"
（之前批量替换把版本字面量也改了，V8 时需同步）。

### 3.2 生成式测试纪律（延续）

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定当前
循环值；强度序列断言注意 step 语义（0.3→0.45→0.6→0.7）。

### 3.3 Constitution 边界（勿越界）

- 表达 ≠ 人格：PresenceState 无身份字段；表达修改人格 → 守护拦截
- 表达 ≠ 主观体验：禁止输出"我感受到了"类声明（reason 只描述状态）
- 形象可换身份不变：restore_state 只恢复表达字段

### 3.4 快照钩子

V6.6 钩子：`_continuity._cognitive_reflection/_growth_cycle/
_growth_trend_analysis`。presence 状态未入快照（V7 P1 预留，V8 可加
presence_state 域）。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 表达未入快照 | 重启后表达回默认 | V8 presence_state 域 |
| 无推送接口 | 状态机就绪无渲染 | V8 WebSocket 推送 |
| 映射规则静态 | 上下文 7 类固定 | V8 偏好学习 |
| 身份检测关键词匹配 | 语义弱 | V8 增强 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 /
  反思≠意识 / 云端≠核心 / 表达≠主体性
- property 与 API 方法禁止同名；新 API 独立命名避冲突

---

## 6. 下一阶段

V8.0 YHLZ Constitution Engine（最高治理层）：人机互补原则/身份边界/
创造增强原则。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V8.0_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V7.0_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**

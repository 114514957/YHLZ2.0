# YHLZ Embodied AI V4.0 下一步开发 Prompt

## YHLZ Engineering Next Development Prompt V4.0


版本：

YHLZ Embodied AI V4.0


依据：

- YHLZ AI工程开发习惯 Prompt V1.0
- YHLZ Vision Foundation V1.0
- YHLZ Vision Perception V1.0
- YHLZ Vision Understanding V1.0
- YHLZ Vision Memory V1.0 验收报告
- YHLZ Personality Engine V3.4 验收报告
- YHLZ Vision Action V1.0 验收报告


---

# 一、当前系统状态分析


## 角色

你现在是 YHLZ 多模态 AI Companion 项目的长期维护高级工程师。

你的职责不是简单写代码，而是完成完整工程闭环：


需求分析 → 架构设计 → 开发实现 → 自动测试 → 验收评估 → 生成报告 → 下一阶段规划


当前开发必须遵循：


稳定开发 / 增量迭代 / 可测试 / 可维护 / 可扩展


---

# 二、当前系统能力


## 1. Voice Infrastructure (V2.1 ~ V2.3) 已完成

- Voice Pipeline / Voice Identity / TTS Adapter (Qwen3 / GPT-SoVITS / Mock)
- Quality Gate / Permission / Task System / Metrics / Security / Lifecycle


## 2. Agent Core (V3.0) 已完成

- Agent Brain (ReAct) / Planner / Reasoning / Tool System / Plugin SDK
- LLM Adapter (OpenAI 兼容 / Mock) / Memory Interface (SQLite + Manager + 短期记忆 + 自动提取 + 衰减)
- Agent Service (单例) / Agent API


## 3. Vision Foundation V1.0 已完成

- VisionFrame / VisionSource / VisionPermission / Screen / Camera / Mock Adapter
- Vision Manager / Service / Permission Checker / Logger


## 4. Vision Perception V1.0 已完成

- OCR (PaddleOCR / Tesseract / Mock) / Detection (YOLO / Mock)
- PerceptionResult (DetectedText / DetectedObject) / Manager / Service / Permission / Logger
- Agent 工具 (read_screen_text / detect_objects) / 11 个 API 端点


## 5. Vision Understanding V1.0 已完成

- VLMAdapter + Provider (Mock / OpenAI 兼容 Qwen-VL)
- UnderstandingResult (scene_type / description / subjects / summary)
- Agent 工具 (describe_scene / answer_visual) / 10 个 API 端点


## 6. Vision Memory V1.0 已完成

- VisualMemoryRecord / MemoryQuery / InMemory + SQLite 双 Store (WAL / 懒加载)
- Memory Manager / Service / Permission (默认拒绝) / Logger (save_latency / query_latency / memory_count / hit_rate)
- 只记忆结构化结果, 禁止原始图像入库
- Agent 工具 (search_visual_memory) / 14 个 API 端点
- 专项 164 / Vision 全量 663 / Agent 131 全过 (Failed=0)


## 7. Personality Engine V3.4 已完成

- PersonalityProfile (五维: friendliness / humor / rigor / warmth / conciseness) + 偏好 + 行为准则
- InMemory + SQLite 双 Store (表 personality_profiles, 数据独立存储)
- Personality Service / Permission (默认拒绝, 敏感字段过滤) / Logger (load_latency / switch_latency / consistency_score / profile_count)
- 默认人格自动创建 / 互斥切换 / 风格生成 (personality_style) / 一致性评估 (assess_consistency) / 人格上下文 (build_persona_context)
- Agent 工具 (get_personality_style) / 15 个 API 端点
- 专项 137 / Vision 全量 663 / Agent 131 全过 (Failed=0)


## 8. Vision Action V1.0 已完成

- ActionRequest (action_id / action_type / target / parameters / reason / confidence / risk_level) + ActionStatus (pending / approved / running / ok / denied / invalid / awaiting_confirm / cancelled / error / unsupported / timeout)
- ActionType: open / navigate / check / query / report / execute / custom; RiskLevel: low / medium / high
- 分层架构: Interface → Service → Manager → Adapter (Executor), 严禁跨层调用
- Validator 字段级校验 / Permission (默认拒绝 + 规则驱动风险等级 + 高风险确认 awaiting_confirm)
- Mock Executor (simulated=True 绝对安全) / Real Executor 占位 (is_available=False, V1.0 禁止自动控制电脑)
- Logger + Metrics (action_count / success_rate / approval_rate / execution_latency / failure_rate) + 行动历史 (in-memory)
- Action Planner (suggest_actions: 理解结果 → 行动建议)
- Agent 工具 (request_action, category=action) / 10 个 /action/* 端点
- 专项 151 / Personality 137 / Vision 663 (2 skip) / Agent 131 全过 (Failed=0)
- 端到端冒烟 16 场景全过 (默认拒绝 / 开启 / 高风险确认 / 确认执行 / 历史 / 指标 / 日志 / 取消 / 非法类型 / 工具注册 / 重置)


---

# 三、本阶段任务: Embodied AI V4.0 (具身智能层)


## 任务背景

Vision Action V1.0 已建立完整的行动基础设施（请求 / 校验 / 风险评估 / 确认 / 执行器抽象 / 历史 / 指标），
但真实执行能力处于占位禁用状态 (Real Executor is_available=False)。

Embodied AI V4.0 的目标：在绝对安全的前提下，打通"看见 → 理解 → 记住 → 人格 → 规划 → 行动"的完整闭环，
让 YHLZ 具备受控的具身行动能力（真实桌面操作），并引入：

- 行动规划 (Action Planning)：LLM 驱动的多步骤任务分解与执行序列编排
- 人机协同 (Human-in-the-loop)：每步执行前可预览 / 确认 / 回滚
- 行动记忆 (Action Memory)：任务级行动历史结构化入库（SQLite），与视觉记忆、人格数据相互独立
- 沙箱执行 (Sandbox)：高风险动作在沙箱 / 预览模式验证后放行


## 核心原则

1. 不修改 Agent Core / Voice / Vision / Personality 既有模块代码 (只新增, 只增量接入)
2. 安全为第一优先级: 真实执行能力默认关闭, 任何真实动作必须显式开启 + 显式授权
3. 分层架构: Interface → Service → Manager → Adapter, 严禁跨层调用
4. 权限默认拒绝: 真实执行 (embodied_enabled=False 默认); 高风险动作双确认
5. Mock 优先: YHLZ_EMBODIED_TEST_MODE=true 时全部走 Mock (不产生真实鼠标键盘事件)
6. 可回滚: 每次真实行动前记录前状态, 支持 undo / 还原
7. 配置驱动: 所有阈值 / 路径 / 开关进 config (embodied_* 前缀)
8. 全类型注解 + 中文注释 + RLock 线程安全 + 日志完整
9. 数据独立存储, 绝不写入 Agent Memory / Personality 数据
10. 行动可取消 / 可超时 / 可暂停 (长任务)


## P0: 核心层 (必须完成)

### 1. Embodied Schema (schema.py)

- EmbodiedTask: task_id / intent / steps (EmbodiedStep[]) / priority / status / created_at
- EmbodiedStep: step_id / action_type / target / parameters / expected_result / confirm (是否需确认) / status
- EmbodiedTaskStatus: pending / planned / approved / running / paused / ok / cancelled / error
- EmbodiedResult: task_id / step_id / action_id / status / output / error / latency_ms
- 复用 Vision Action 的 ActionRequest / ActionStatus / RiskLevel 语义 (action_type: open / navigate / check / query / report / execute / custom)

### 2. Embodied Interface (interface.py)

- EmbodiedPlanner ABC: plan(intent, context) → EmbodiedTask (行动规划器, 支持规则 / LLM 双实现)
- EmbodiedExecutor ABC: execute_step(step) / pause / resume / cancel / undo / is_available
- 异常: EmbodiedPlannerError / EmbodiedExecutorError

### 3. Planner (planners/)

- rule_planner.py: 规则驱动规划 (意图 → 固定步骤序列, 如"打开 X 并检查状态" → [open X, check status])
- llm_planner.py: LLM 驱动规划 (OpenAI 兼容 / Mock Provider, 复用 Vision Understanding 的 Provider 模式)
- 规划结果必须经过 Schema 校验 (步骤 action_type 白名单 / 参数合法性), 非法规划直接拒绝

### 4. Embodied Manager (manager.py)

- EmbodiedManager: Planner 注册表 + Executor 注册表 + 任务生命周期 (create → plan → approve → run → finish)
- 默认注册: Mock Planner / Mock Executor; LLM Planner / Real Executor (is_available 探测)
- 任务队列: 单任务串行执行 (防止并发真实操作), 支持暂停 / 恢复 / 取消
- 单例 get_manager / reset_manager

### 5. Embodied Permission (permission.py)

- EmbodiedPermission: embodied_enabled (默认 False) / allow_real_execution (默认 False) / allow_high_risk (默认 False) / confirm_every_step (默认 True) / max_steps_per_task (默认 10) / cooldown_seconds (默认 2.0) / undo_enabled (默认 True)
- PermissionChecker: check_task(task) / check_step(step) / check_real_execution()
- 真实执行三重校验: 功能开关 → 风险等级 → 用户确认 (confirm_every_step)
- 高频防护: 同类型步骤最小间隔 (cooldown) / 单任务步数上限

### 6. Embodied Logger (logger.py)

- EmbodiedLogEntry: timestamp / event (plan / approve / start / success / fail / pause / resume / cancel / undo / exception) / task_id / step_id / status / latency_ms / error / metadata
- EmbodiedLogger: 指标 task_count / step_count / success_rate / approval_rate / avg_task_latency / plan_failure_count

### 7. Embodied Store (stores/)

- memory_store.py: InMemoryEmbodiedTaskStore (容量上限, 稳定排序)
- sqlite_store.py: SQLiteEmbodiedTaskStore (表 embodied_tasks, WAL, 懒加载, env YHLZ_EMBODIED_DB 覆盖路径)
- 只存结构化任务/步骤结果, 禁止原始截图入库

### 8. Embodied Service (service.py)

- EmbodiedService: 组合 Manager + Permission + Logger + Store
- submit(intent, context): 规划 → 校验 → 待确认 (awaiting) → 返回 task_id
- approve(task_id) / execute(task_id) / pause / resume / cancel / undo(step_id)
- execute 逐步骤: 权限校验 → 风险校验 → 频控 → Executor 执行 → 记录 → 下一步
- status() 返回 version="4.0.0" / planners / executors / permission / counts
- 单例 get_service / reset_service


## P1: 接入层 (必须完成)

### 1. Agent Tool (tools.py)

- 工具: submit_task (category=embodied) — 提交具身任务 (intent 意图文本 + 可选 context)
- 工具: task_status (category=embodied) — 查询任务 / 步骤状态
- 工具: approve_task (category=embodied) — 确认待执行任务 (human-in-the-loop)
- 输出标准化 JSON 字符串 (success / task_id / status / steps)
- 内部只调用 EmbodiedService, 不直接触碰 Planner / Executor

### 2. Vision Action 融合 (action/planners/action_planner.py 扩展)

- suggest_actions 升级: 当理解结果触发需要"多步骤"的行动场景时, 返回 EmbodiedTask 建议 (而非单步 action)
- 单步行动保持 Vision Action V1.0 行为不变 (向后兼容)
- 任务级结果回写: EmbodiedTask 完成后, 可选生成 report 行动总结

### 3. Config 驱动 (config.py)

- embodied_enabled (默认 false)
- embodied_allow_real_execution (默认 false)
- embodied_allow_high_risk (默认 false)
- embodied_confirm_every_step (默认 true)
- embodied_max_steps_per_task (默认 10)
- embodied_cooldown_seconds (默认 2.0)
- embodied_db_path (默认 backend/data/embodied_tasks.db)
- embodied_test_mode (YHLZ_EMBODIED_TEST_MODE, 默认 false)
- embodied_tool_timeout (默认 10.0)

### 4. API 端点 (main.py)

- 启动时注册工具 (register_embodied_tools)
- 端点 (参照 /personality/* 与 /action/* 模式, _get_embodied_service() 懒加载):
  - GET  /embodied/status
  - GET  /embodied/permission / POST /embodied/permission / POST /embodied/reset-permission
  - POST /embodied/tasks (提交意图) / GET /embodied/tasks (检索)
  - GET  /embodied/tasks/{task_id} (详情含步骤)
  - POST /embodied/tasks/{task_id}/approve (确认)
  - POST /embodied/tasks/{task_id}/execute (开始执行)
  - POST /embodied/tasks/{task_id}/pause / resume / cancel
  - POST /embodied/tasks/{task_id}/steps/{step_id}/undo (回滚)
  - GET  /embodied/logs / DELETE /embodied/logs
  - GET  /embodied/planners / GET /embodied/executors (可用列表)


## 验收标准

```
Embodied 专项:   Total: 120+   Passed: 100%   Failed: 0   Skipped: 0
Vision Action:   Failed: 0 (包含既有 151)
Personality:     Failed: 0 (包含既有 137)
Vision 全量回归: Failed: 0 (包含既有 663)
Agent 回归:      Failed: 0 (包含既有 131)
```

端到端冒烟 (FastAPI TestClient):
- 默认拒绝: submit_task → denied, 不产生任何任务
- 开启权限 + Mock: submit("打开计算器并检查状态") → plan → awaiting → approve → execute → ok (Mock 记录)
- 高风险任务: 未授权 → denied; 授权 + 逐步骤确认 → ok
- 长任务: 执行中 pause → resume → cancel
- undo: 回滚指定步骤 (Mock 记录 undo 事件)
- 任务历史 / 日志 / Planner / Executor 列表 / 清空
- Agent 工具 submit_task / task_status / approve_task 全链路 (Mock)


---

# 四、工程规范


## 目录结构 (新增)

```
backend/embodied/
├── __init__.py
├── schema.py
├── interface.py
├── manager.py
├── permission.py
├── logger.py
├── service.py
├── tools.py
├── planners/
│   ├── __init__.py
│   ├── rule_planner.py      # 规则驱动规划
│   └── llm_planner.py       # LLM 驱动规划 (OpenAI 兼容 / Mock)
├── executors/
│   ├── __init__.py
│   ├── mock_executor.py     # Mock: 只记录, 不产生真实事件
│   └── real_executor.py     # 真实执行 (需 pyautogui, is_available 探测, 默认禁用)
├── stores/
│   ├── __init__.py
│   ├── memory_store.py      # InMemoryEmbodiedTaskStore
│   └── sqlite_store.py      # SQLiteEmbodiedTaskStore
└── tests/
    ├── test_schema.py / test_interface.py / test_planners.py / test_executors.py
    ├── test_manager.py / test_permission.py / test_logger.py
    ├── test_memory_store.py / test_sqlite_store.py / test_service.py
    ├── test_tools.py / test_integration.py
```

## 开发约束

1. 严禁跨层调用 (Service 只经 Manager, 不直接调 Planner / Executor)
2. 禁止修改 Agent Core / Voice / Vision / Personality 既有模块代码
3. 行动数据与视觉记忆 / 人格数据独立存储 (绝不写入 Agent Memory)
4. 任务执行必须可暂停 / 可恢复 / 可取消 / 可回滚 (undo)
5. Mock 模式必须绝对安全: 不移动鼠标 / 不按键 / 不输入 (单元测试不得依赖真实桌面)
6. 测试隔离: 所有测试在 YHLZ_EMBODIED_TEST_MODE=true 下运行, 环境变量修改 try/finally 成对恢复
7. 真实执行 (Real Executor) 必须默认不可用 (is_available=False), 需 pyautogui 安装 + 显式配置才启用
8. 交付物写入 D:\YHLZ2.0\下载物象\任务计划\二阶段\:
   - YHLZ_Embodied_AI_V4.0_验收报告.md
   - YHLZ_XXXX_下一步开发Prompt.txt (Embodied AI V4.0 之后的下一阶段规划, 由你评估决定: 建议进入 多模态统一任务记忆 / 自主行动学习(带监督) / YHLZ 对外能力开放平台 之一)

## 依赖检查

- pyautogui 若未安装: Real Executor 优雅降级 (is_available=False + 日志), 不阻塞启动
- LLM Planner 复用 Vision Understanding 的 Provider 模式 (Mock 默认, 禁止新增硬依赖)
- 禁止引入未在 requirements 中的新依赖到核心路径 (可选导入)


---

# 五、验收输出

1. YHLZ_Embodied_AI_V4.0_验收报告.md (格式参照 YHLZ_Vision_Action_V1.0_验收报告.md)
2. 下一阶段开发 Prompt txt
3. 最终交付总结 (向用户输出: 完成内容 / 测试数据 / 架构图 / 使用方法 / 下一阶段建议)


**验收通过标准: 专项 + 全量回归 Failed=0, 端到端冒烟全部通过, 架构/权限/集成验收清单全勾选。**

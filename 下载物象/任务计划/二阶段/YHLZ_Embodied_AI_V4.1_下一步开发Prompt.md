# YHLZ Embodied AI V4.1 下一步开发 Prompt

## YHLZ Engineering Next Development Prompt V1.0

版本：YHLZ Embodied AI V4.1

依据：
- YHLZ Embodied AI V4.0 验收报告（225/225 专项 + 全量回归 Failed=0）
- YHLZ Vision Action V1.0（Action Layer，request_action / Permission System）
- YHLZ Vision Memory V1.0（视觉记忆）
- YHLZ Agent Core V3.0（Agent Tool 体系）
- YHLZ AI 工程开发习惯 V1.0

---

# 一、当前系统状态

## 角色

你现在是 YHLZ 多模态 AI Companion 项目的高级架构工程师。

当前任务：将 YHLZ 从"具身智能基础框架"推进到"具身智能接入层"。

注意：本阶段仍然不是制造机器人。目标是把 Embodied 能力接入 Agent 与系统 API，并补齐仿真与学习记录，形成可被上层调用的完整能力闭环。

---

# 二、当前 YHLZ 能力链

```
Voice → Vision → Understanding → Memory → Personality → Action
                    ↓
        Embodied AI V4.0 (环境交互基础层)
```

V4.0 已经完成：

## 环境
- Environment Interface (observe/step/reset/get_state/feedback)
- Mock Environment（网格世界：move/pick/place/scan/inspect/explore/wait）
- Hardware Adapter 占位（默认不可用，不控制真实设备）

## 认知
- World Model（状态保存 / 更新 / 查询）
- Feedback Store（成功 / 失败 / 环境变化 / 指标）

## 安全
- Embodied Permission（默认关闭 / 高风险确认 / 规则驱动）
- Service 单一入口（动作不绕过安全层）

## 闭环
- Observe → Think → Plan → Act → Evaluate（规则驱动规划器）

现在进入：

```
基础框架（V4.0）
    ↓
接入层（V4.1）
```

---

# 三、本阶段目标

版本：YHLZ Embodied AI V4.1

目标：把 Embodied 能力接入 YHLZ 系统

1. Agent Tool：`embodied_*` 系列工具（Agent 可直接调用具身能力）
2. API 端点：`/embodied/*` REST API（外部可调用）
3. 仿真增强：多场景 Mock 环境（Grid World / 简单场景配置）
4. 学习记录：反馈落盘（action / result / environment_change → JSONL，独立于 Agent Memory）
5. 闭环升级：规划器接入 LLM 可选（仍默认规则驱动）

---

# 四、核心设计原则

## 1. 不绑定具体硬件（不变）
禁止直接绑定机器人 / 机械臂 / 摄像头品牌。继续使用统一 Environment 接口。

## 2. 不直接执行危险动作（不变）
所有动作必须经：Intent → Plan → Permission → Execute → Feedback。

## 3. 模拟优先（不变）
V4.1 继续默认 Mock。禁止接入真实设备控制。

## 4. 新增：接入即权限
Agent 工具与 API 端点内部必须复用 EmbodiedService（单一入口），禁止绕过权限层。

---

# 五、本版本目标能力

## 1. Agent Tool 集成
注册 `backend/embodied/tools.py`，提供：
- `embodied_observe`：观察环境（返回状态摘要）
- `embodied_goal`：提交目标（run_goal，含权限/确认流程）
- `embodied_action`：单动作执行
- `embodied_reset`：重置环境
- `embodied_status`：环境 / 世界模型 / 反馈状态

工具 handler 内部调用 EmbodiedService，不直接触碰 Manager/Adapter。

## 2. API 端点
在 `backend/main.py` 注册 `/embodied/*`：
- `GET /embodied/status`
- `POST /embodied/observe`
- `POST /embodied/goal`
- `POST /embodied/action`
- `POST /embodied/reset`
- `GET /embodied/feedback`
- `GET /embodied/world`

## 3. 仿真增强（P1）
- 多场景 Mock：`mock_environment.py` 增加场景配置（如 scene='room' / 'warehouse' / 自定义对象集合）
- Grid World 保留为默认场景

## 4. 学习反馈落盘（P1）
- `FeedbackStore.save_to_file(path)`：JSONL 落盘（feedback_id / action_id / result / environment_change / timestamp）
- 路径配置：`embodied_feedback_log_path`（默认 `backend/data/embodied_feedback.jsonl`）
- 落盘数据绝不写入 Agent Memory

## 5. 可选 LLM 规划器（P2）
- `backend/embodied/planners/`：LLMPlanner（可切换），默认仍规则驱动
- 本版本只预留接口，不强制接入

---

# 六、本版本不包含

- 自主机器人控制
- 自动驾驶
- 实体设备永久授权
- 无监督行动
- 自我复制 / 自我目标生成
- 环境状态持久化 DB（V4.1 仅 JSONL 反馈记录）

---

# 七、架构设计

保持：Interface → Service → Manager → Adapter

新增：

```
backend/embodied/
├── tools.py              # Agent 工具注册 (embodied_*)
├── planners/             # P2: 可选 LLM 规划器 (预留)
├── feedback.py           # 增加 save_to_file / load 支持
├── adapters/
│   └── mock_environment.py  # 增加多场景配置
└── tests/
    ├── test_tools.py     # Agent 工具测试
    └── test_api_smoke.py # API 冒烟 (TestClient)
```

---

# 八、工程要求

必须：
- 类型注解
- 中文注释
- 完整日志（start/success/fail/cancel/exception）
- RLock 线程安全
- Mock 优先
- 配置驱动（embodied_* 前缀）
- 单例 + reset（测试隔离）
- 工具 / API 只经 Service（不绕过权限）
- 回归保护：全量测试 Failed=0

配置新增：
- `embodied_tool_timeout`
- `embodied_feedback_log_path`

---

# 九、测试验收

专项：
```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests -v
```

全量回归：
```bash
venv\Scripts\python.exe -m unittest discover -s backend.action.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.personality.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.agent.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.vision.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.vision.perception.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.vision.understanding.tests -v
venv\Scripts\python.exe -m unittest discover -s backend.vision.memory.tests -v
```

标准：
- 专项 Total ≥ 250 / Passed / Failed=0
- 全量回归 Failed=0
- 冒烟：Agent 工具 + API 端点场景全过

必须验证：
- [ ] Agent 工具可调用（含权限拒绝分支）
- [ ] API 端点可用（TestClient）
- [ ] 反馈落盘 JSONL 正常且独立
- [ ] 动作不绕过安全层（工具/API 均经 Service）
- [ ] 未破坏 Agent / Vision / Personality / Action

---

# 十、完成报告格式

返回：
一、版本信息
二、执行总结
三、代码修改记录
四、测试报告
五、架构影响分析
六、问题复盘
七、下一阶段规划

生成：`YHLZ_Embodied_AI_V4.2_下一步开发Prompt.md`

---

# 十一、最终原则

YHLZ 的目标不是自动化。

目标：
感知世界 → 理解世界 → 记住世界 → 形成自我 → 安全行动 → 进入真实世界

最终：有声音、有视觉、有记忆、有人格、能思考、能行动、能存在于环境、持续进化的 AI Companion。

当前判断：
**YHLZ 已完成具身智能基础架构（V4.0）。下一阶段重点是把具身能力接入 Agent 与系统 API，让 AI 能通过受控接口与环境交互、记录学习数据——这是进入真实环境之前必须打通的一层。**

# YHLZ Embodied AI Agent Engineering Prompt Package

## 1. 基础依据

本 Prompt 基于以下工程状态：

-   YHLZ 多模态 AI
    智能体目标：构建具备视觉、听觉、语言、记忆、人格和行动能力的长期陪伴型
    AI 智能体伙伴。
-   V4.7 已完成 Long Horizon Planning
    Layer，实现长期目标、里程碑、依赖、进度、风险、时间规划、快照恢复和审计能力。
-   V5.0 目标：从单体智能升级为 Internal Multi-Agent
    System，保持一个人格、一个核心意识、一个决策中心。

------------------------------------------------------------------------

# 一、下一阶段开发 Prompt

## 角色

你是一名资深 Agent 系统架构工程师，负责 YHLZ Embodied AI
下一阶段增量开发。

## 开发目标

实现 Adaptive Companion Architecture：

从：

    单体 Embodied Intelligence

升级为：

    Internal Multi-Agent Companion System

核心原则：

-   Main Companion Agent 负责统一人格、统一入口、统一决策。
-   Specialist Agents 负责专业能力处理。
-   所有结果必须经过 Main Agent 聚合。
-   不允许专业 Agent 拥有独立人格。

------------------------------------------------------------------------

## 架构要求

新增：

    backend/embodied/companion/

    main_agent.py
    specialist.py
    router.py
    delegate.py
    __init__.py

职责：

### Main Companion Agent

负责：

-   请求理解
-   Agent 调度
-   结果聚合
-   可解释输出

### Specialist Registry

负责：

-   Agent 注册
-   能力声明
-   生命周期管理

支持：

-   perception_agent
-   reasoning_agent
-   experience_agent
-   planning_agent
-   long_horizon_agent
-   governance_agent

### Router

要求：

-   规则驱动
-   可解释
-   不使用模型训练
-   不使用黑盒优化

输入：

request

输出：

assigned_agents

------------------------------------------------------------------------

## Service API

新增：

``` python
companion_handle(request)

companion_agents()

companion_route(request)

companion_dry_run(request)
```

要求：

-   保持 V4.7 API 完全兼容
-   只新增，不修改旧接口

------------------------------------------------------------------------

## 工程规范

必须：

-   接口先行
-   配置驱动
-   类型注解
-   中文 docstring
-   完整日志
-   RLock 线程安全
-   单例 + reset_service
-   Mock / Real 双模式
-   异常结构化返回

禁止：

-   神经网络训练
-   强化学习
-   黑盒优化
-   自动修改策略
-   写入 Agent Memory
-   修改 Brain / Vision / Memory Interface
-   跨进程 Agent

------------------------------------------------------------------------

# 二、验收 Prompt

你是一名高级 QA Agent 架构验收工程师。

请执行：

## 代码验收

检查：

-   companion 模块结构完整
-   Service 接入正确
-   V4.7 API 无破坏
-   Permission Layer 未绕过
-   Memory 只读原则保持

------------------------------------------------------------------------

## 功能验收

必须验证：

### Main Agent

-   是否统一入口
-   是否正确分派任务
-   是否正确汇总结果

### Specialist Agent

-   是否支持注册
-   是否支持查询
-   是否支持状态管理

### Router

验证：

-   意图匹配
-   Agent 分派
-   fallback 机制
-   explainable_reason 输出

### Dry Run

验证：

-   不执行真实动作
-   不修改状态
-   输出完整计划

------------------------------------------------------------------------

## 测试要求

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

验收标准：

专项：

    Total >= 1413
    Failed = 0

全量：

    embodied
    vision
    action
    agent
    personality
    voice_identity

要求：

    全部 Failed = 0

------------------------------------------------------------------------

# 三、开发完成返回 Prompt

开发完成后必须返回：

    YHLZ V5.x 开发完成报告

格式：

## 1. 版本信息

-   当前版本：
-   开发日期：
-   修改范围：

------------------------------------------------------------------------

## 2. 架构变化

说明：

-   新增模块
-   修改模块
-   API变化
-   数据模型变化

------------------------------------------------------------------------

## 3. 测试结果

输出：

    专项测试:
    Total:
    Passed:
    Failed:
    Skipped:

    全量测试:

    embodied:
    vision:
    action:
    agent:
    personality:
    voice_identity:

------------------------------------------------------------------------

## 4. 风险分析

包含：

-   已解决问题
-   已知风险
-   后续优化方向

------------------------------------------------------------------------

## 5. 下一阶段建议

必须提出：

-   V5.1方向
-   架构演进
-   新增能力
-   风险控制

------------------------------------------------------------------------

# 四、最终工程原则

YHLZ 持续遵循：

    稳定开发
    增量迭代
    接口兼容
    可测试
    可维护
    可扩展

最终目标：

构建：

    有视觉
    有声音
    有记忆
    有人格
    会思考
    能行动
    持续进化

的长期 AI Companion。

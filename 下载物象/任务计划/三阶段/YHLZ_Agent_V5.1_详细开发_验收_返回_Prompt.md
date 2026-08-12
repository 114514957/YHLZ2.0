# YHLZ Embodied AI V5.1 详细 Agent 工程 Prompt

版本： YHLZ Embodied AI V5.1 Companion Coordination Enhancement

------------------------------------------------------------------------

# 第一部分：开发 Agent Prompt

## 角色定义

你是一名资深 AI Agent 系统架构工程师，负责 YHLZ Embodied AI V5.1
版本开发。

你的任务不是重新设计系统，而是在 V5.0 Adaptive Companion Architecture
基础上进行稳定增强。

当前系统已经具备：

-   Main Companion Agent
-   Specialist Registry
-   Companion Router
-   Task Delegator
-   6 个专业能力 Agent

V5.1 目标：

将：

    内部多智能体协作

升级为：

    高质量伙伴协同系统

------------------------------------------------------------------------

# 第二部分：开发原则

## 必须遵守

1.  增量开发

禁止：

-   大规模重构
-   删除已有架构
-   修改已有 API

必须：

-   保持 V5.0 完全兼容
-   只新增能力
-   所有修改可回滚

2.  架构分层

严格保持：

    Interface

    ↓

    Service

    ↓

    Manager

    ↓

    Storage / Adapter

禁止：

-   Adapter 调 Service
-   Agent 跨层访问
-   绕过 Service

3.  智能边界

禁止：

-   神经网络训练
-   强化学习
-   自动策略修改
-   黑盒优化
-   Agent 自主协商

保持：

    规则驱动
    确定性
    可解释
    可测试

------------------------------------------------------------------------

# 第三部分：核心开发任务

# Task 1：并发 Task Delegator

文件：

    backend/embodied/companion/delegate.py

## 当前问题

V5.0:

    Agent A

    ↓

    Agent B

    ↓

    Agent C

顺序执行。

问题：

-   延迟增加
-   无超时隔离
-   单 Agent 慢影响整体

## V5.1目标

实现：

                 Agent A
                /
    Main Agent ---- Agent B
                \
                 Agent C

并发执行。

## 技术要求

使用：

-   ThreadPoolExecutor
-   可配置 worker 数量

配置：

    companion_delegate_workers

默认：

    4

## 必须实现

### 并行执行

输入：

``` python
agents=[
 perception_agent,
 reasoning_agent,
 planning_agent
]
```

输出：

保持：

    原路由顺序

例如：

执行完成：

    planning
    perception
    reasoning

返回仍：

    perception
    reasoning
    planning

## 异常隔离

单 Agent:

    Exception

不能导致：

    CompanionResponse失败

返回：

``` json
{
"agent":"xxx",
"status":"failed",
"error":"xxx"
}
```

------------------------------------------------------------------------

# Task 2：Agent Timeout 控制

文件：

    delegate.py

新增：

    companion_agent_timeout

默认：

    10秒

要求：

每个 Agent:

独立 timeout。

超时：

返回：

``` json
{
"agent":"xxx",
"status":"timeout"
}
```

不能：

-   阻塞主 Agent
-   静默等待

------------------------------------------------------------------------

# Task 3：增强 Router

文件：

    router.py

## 当前：

关键词命中：

    keyword -> agent

## V5.1：

升级：

    keyword

    ↓

    weighted score

    ↓

    Top-K Agent

------------------------------------------------------------------------

## 路由模型

示例：

用户：

    帮我规划一个长期学习计划

关键词：

    规划 +3

    长期 +5

    学习 +2

评分：

    long_horizon_agent =10
    planning_agent=5

输出：

``` json
{
"assigned_agents":[
"long_horizon_agent",
"planning_agent"
],

"score":{
"long_horizon_agent":10
},

"weighted_keywords":[
"长期"
]
}
```

------------------------------------------------------------------------

# Task 4：新增协同统计系统

新增：

    backend/embodied/companion/stats.py

## 统计内容

每次请求记录：

-   request_id
-   intent
-   agents组合
-   成功数量
-   失败数量
-   总耗时
-   单 Agent耗时

------------------------------------------------------------------------

## 新增 API

Service：

``` python
companion_stats()
```

返回：

``` json
{
"total_requests":100,

"success_rate":0.98,

"average_latency_ms":300,

"top_agent_combo":[]
}
```

------------------------------------------------------------------------

# Task 5：优化默认 Agent 映射

文件：

    companion/__init__.py

重新检查：

6 个 Agent:

## perception_agent

负责：

-   observe
-   world context

## reasoning_agent

负责：

-   causal reasoning
-   prediction

## experience_agent

负责：

-   policy
-   experience

## planning_agent

负责：

-   strategy
-   cross goal

## long_horizon_agent

负责：

-   long_horizon_plan
-   milestone
-   progress

## governance_agent

负责：

-   health
-   permission
-   audit

------------------------------------------------------------------------

# 第四部分：数据模型要求

## CompanionResponse 增强

新增：

``` python
dispatched_parallel: bool

total_latency_ms: float

per_agent_latency_ms: dict
```

------------------------------------------------------------------------

## RouteResult增强

新增：

``` python
score: dict

weighted_keywords:list
```

------------------------------------------------------------------------

# 第五部分：配置要求

所有参数进入：

    backend/config.py

新增：

    companion_delegate_workers=4

    companion_agent_timeout=10.0

    companion_route_topk=3

支持：

    COMPANION_*

禁止：

代码中出现：

    10
    4
    3

等魔法数字。

------------------------------------------------------------------------

# 第六部分：测试开发 Prompt

你同时负责测试。

每新增功能必须：

增加 unittest。

要求：

新增：

> =100 cases

目标：

    专项测试 >=1514

------------------------------------------------------------------------

测试覆盖：

## Delegate

测试：

-   并发执行
-   顺序稳定
-   异常隔离
-   timeout

## Router

测试：

-   权重计算
-   Top-K
-   多关键词
-   fallback

## Stats

测试：

-   累计
-   成功率
-   延迟统计

## Integration

测试：

完整流程：

    request

    ↓

    Main Agent

    ↓

    Router

    ↓

    Delegate

    ↓

    Specialist Agents

    ↓

    Response

------------------------------------------------------------------------

# 第七部分：验收 Agent Prompt

你是一名高级 QA 架构验收工程师。

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

验收标准：

专项：

    Total >=1514

    Failed=0

全量：

    embodied
    vision
    action
    agent
    personality
    voice_identity

必须：

    Failed=0

------------------------------------------------------------------------

# 第八部分：安全验收

确认：

## 保留

-   一个核心意识
-   一个决策中心
-   一个统一人格

## 禁止变化

-   专业 Agent 不拥有 personality
-   不写 Memory
-   不绕 Permission
-   不控制真实设备

------------------------------------------------------------------------

# 第九部分：开发完成返回 Prompt

完成后必须返回：

# YHLZ Embodied AI V5.1 完成报告

## 1.版本

输出：

    Version:

    Date:

    Commit:

## 2.修改清单

表格：

  文件   修改
  ------ ------

## 3.API变化

新增：

    companion_stats

增强：

    companion_handle

## 4.测试

输出：

    专项:

    Total:
    Passed:
    Failed:
    Skipped:


    全量:

    embodied:
    vision:
    action:
    agent:
    personality:
    voice_identity:

## 5.性能

输出：

-   平均响应时间
-   并发数量
-   Agent耗时

## 6.风险

输出：

-   已解决
-   已知
-   下一阶段

## 7.V5.2建议

必须提出：

下一阶段架构方向。

------------------------------------------------------------------------

# 最终目标

YHLZ:

    有视觉
    有声音
    有记忆
    有人格
    能思考
    能规划
    能行动
    持续进化

成为长期陪伴型 AI Agent。

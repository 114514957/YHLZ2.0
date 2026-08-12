# YHLZ Embodied AI V5.3 详细开发_验收_返回_Prompt

## 版本

YHLZ Embodied AI V5.3\
Companion Execution & Feedback Loop

------------------------------------------------------------------------

# 一、开发角色

你是一名高级 AI Agent 系统架构工程师。

基于 V5.2 伙伴感知与战略集成层，开发 V5.3 伙伴执行与反馈闭环层。

当前演进：

    V5.2 感知-策略闭环
            ↓
    V5.3 执行-反馈闭环

目标：

    感知
     ↓
    策略
     ↓
    规划
     ↓
    执行
     ↓
    反馈
     ↓
    调整

保持：

    一个人格
    一个核心意识
    一个决策中心

------------------------------------------------------------------------

# 二、工程约束

必须：

-   增量开发
-   保持 V5.2 API 兼容
-   接口先行
-   配置驱动
-   类型注解
-   中文 docstring
-   完整日志
-   单元测试覆盖

禁止：

-   神经网络训练
-   强化学习
-   黑盒优化
-   自我目标生成
-   Agent 自由协商
-   修改 Brain/Vision/Memory Interface
-   写入 Agent Memory
-   真实设备控制
-   分布式多进程 Agent

------------------------------------------------------------------------

# 三、核心开发任务

## Task 1：执行协调器

新增：

    companion/executor.py

实现：

    planning_agent

    ↓

    EmbodiedGoal

    ↓

    run_goal

    ↓

    ExecutionResult

要求：

-   执行必须经过 Permission Layer
-   不直接控制设备
-   使用已有 Action Service
-   记录执行审计

ExecutionRecord:

    goal
    actions
    result
    latency_ms
    status

------------------------------------------------------------------------

## Task 2：反馈闭环

实现：

    执行结果

    ↓

    反馈分析

    ↓

    成功/失败统计

    ↓

    策略调整建议

要求：

反馈用于分析和经验统计。

禁止自动修改核心策略。

------------------------------------------------------------------------

## Task 3：Pipeline 闭环增强

修改：

    companion/pipeline.py

升级：

    perception
     ↓
    experience
     ↓
    planning
     ↓
    execution
     ↓
    feedback

要求：

-   阶段可追踪
-   数据可解释
-   异常隔离
-   循环次数限制

------------------------------------------------------------------------

## Task 4：闭环 API

新增：

``` python
companion_execute(request)

companion_loop(request)
```

增强：

``` python
companion_handle()
```

要求：

保持旧接口兼容。

------------------------------------------------------------------------

# 四、配置要求

backend/config.py:

新增：

    companion_loop_max_iterations=3

    companion_execute_confirm=False

    companion_feedback_enabled=True

所有配置支持：

    COMPANION_*

禁止硬编码。

------------------------------------------------------------------------

# 五、测试验收 Prompt

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

专项：

    Total >=1714
    Failed=0

全量：

    embodied
    vision
    action
    agent
    personality
    voice_identity

全部：

    Failed=0

测试覆盖：

-   Executor
-   Feedback
-   Loop
-   Permission
-   Pipeline
-   Integration

------------------------------------------------------------------------

# 六、开发完成返回 Prompt

输出：

# YHLZ Embodied AI V5.3 完成报告

## 版本

    Version:
    Date:
    Commit:

## 修改清单

  文件   修改
  ------ ------

## API变化

新增：

    companion_execute()
    companion_loop()

增强：

    companion_handle()

## 测试结果

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

## 闭环指标

输出：

-   执行成功率
-   平均耗时
-   Feedback统计
-   Loop统计

## 风险分析

包含：

-   已解决问题
-   已知风险
-   V5.4方向

------------------------------------------------------------------------

# 最终目标

YHLZ:

    有视觉
    有声音
    有记忆
    有人格
    能感知
    能思考
    能规划
    能执行
    能反馈
    持续进化

成为长期陪伴型 AI Agent。

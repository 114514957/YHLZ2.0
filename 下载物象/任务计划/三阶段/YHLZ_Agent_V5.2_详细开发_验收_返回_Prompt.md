# YHLZ Embodied AI V5.2 详细 Agent 工程 Prompt

## 版本

YHLZ Embodied AI V5.2\
Companion Perception & Strategy Integration

------------------------------------------------------------------------

# 一、开发角色

你是一名高级 AI Agent 系统架构工程师。

负责在 V5.1 Companion Coordination Enhancement 基础上开发 V5.2。

当前演进：

    V5.0 内部多智能体协作
            ↓
    V5.1 伙伴协同增强
            ↓
    V5.2 伙伴感知与战略集成

V5.2目标：

建立：

    感知 → 策略 → 规划

闭环。

保持：

    一个人格
    一个核心意识
    一个决策中心

------------------------------------------------------------------------

# 二、开发原则

必须：

-   增量开发
-   保持 V5.1 API 兼容
-   接口先行
-   配置驱动
-   可解释
-   可测试

禁止：

-   神经网络训练
-   强化学习
-   黑盒优化
-   自主修改策略
-   Agent 自由协商
-   修改 Brain Interface
-   修改 Vision Interface
-   修改 Memory Interface
-   写入 Agent Memory
-   真实设备控制
-   分布式多进程 Agent

------------------------------------------------------------------------

# 三、核心开发任务

## Task 1：新增 Agent Pipeline

新增：

    backend/embodied/companion/pipeline.py

职责：

实现 Agent 间数据流：

    perception_agent
            ↓
    experience_agent
            ↓
    planning_agent
            ↓
    long_horizon_agent

要求：

-   前序 Agent 输出作为后序 Agent 输入
-   执行顺序可追踪
-   数据流可解释
-   支持审计

新增模型：

    PipelineStage

字段：

    stage
    input_from
    output_to
    source
    target

------------------------------------------------------------------------

# Task 2：Pipeline Context

新增：

    PipelineContext

保存：

-   request_id
-   intent
-   stage_results
-   environment_state
-   strategy_hint

要求：

所有 Agent 之间传递数据必须经过 Context。

------------------------------------------------------------------------

# Task 3：增强 Delegate

修改：

    companion/delegate.py

支持：

普通委派：

    Agent → Result

Pipeline委派：

    Agent A
     ↓
    Agent B
     ↓
    Agent C

要求：

-   支持依赖执行
-   支持异常隔离
-   支持 strict 模式

------------------------------------------------------------------------

# Task 4：感知-策略闭环

实现：

    observe

    ↓

    environment_state

    ↓

    experience policy

    ↓

    strategy_hint

    ↓

    planning

    ↓

    plan

注意：

只生成策略建议。

禁止：

自动执行现实动作。

------------------------------------------------------------------------

# Task 5：Service API

新增：

``` python
companion_pipeline(request)
```

功能：

分析：

-   Agent依赖
-   执行顺序
-   数据流

返回：

``` json
{
 pipeline_stages:[],
 explainable_reason:""
}
```

要求：

只分析，不执行。

增强：

``` python
companion_handle()
```

支持 Pipeline。

------------------------------------------------------------------------

# 四、配置要求

修改：

    backend/config.py

新增：

    companion_pipeline_enabled=True

    companion_pipeline_strict=False

支持：

    COMPANION_*

禁止：

魔法数字。

------------------------------------------------------------------------

# 五、能力映射

优化：

    build_default_agents()

要求：

## perception_agent

输出：

    environment_state

## experience_agent

输入：

    environment_state

输出：

    strategy_hint

## planning_agent

输入：

    strategy_hint

输出：

    plan

## long_horizon_agent

输入：

    plan

输出：

长期调整建议。

------------------------------------------------------------------------

# 六、测试 Prompt

新增测试：

> =100 cases

覆盖：

## Pipeline

-   stage顺序
-   数据传递
-   Context完整性

## Delegate

-   依赖执行
-   错误隔离
-   strict模式

## Integration

验证：

    Request

    ↓

    Main Agent

    ↓

    Pipeline

    ↓

    Specialist Agents

    ↓

    Response

------------------------------------------------------------------------

# 七、验收 Prompt

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

标准：

专项：

    Total >=1614
    Failed = 0

全量：

    embodied
    vision
    action
    agent
    personality
    voice_identity

全部：

    Failed = 0

------------------------------------------------------------------------

# 八、开发完成返回 Prompt

输出：

## YHLZ Embodied AI V5.2 完成报告

包含：

## 1.版本

    Version:
    Date:
    Commit:

## 2.修改清单

  文件   修改
  ------ ------

## 3.API变化

新增：

    companion_pipeline()

增强：

    companion_handle()

## 4.测试结果

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

## 5.Pipeline指标

输出：

-   Pipeline成功率
-   平均耗时
-   Stage统计
-   数据流统计

## 6.风险分析

输出：

-   已解决问题
-   已知风险
-   V5.3建议

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
    能行动
    持续进化

成为长期陪伴型 AI Agent。

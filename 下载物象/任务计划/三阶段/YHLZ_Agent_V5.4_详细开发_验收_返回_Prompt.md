# YHLZ Embodied AI V5.4 专业 Agent 工程 Prompt

## 版本

YHLZ Embodied AI V5.4

## 名称

Companion Self-Correction & Rule Learning Layer

------------------------------------------------------------------------

# 一、开发 Agent 角色

你是一名高级 AI Agent 系统架构工程师。

负责在 YHLZ Embodied AI V5.3 基础上进行 V5.4 增量开发。

演进路线：

    V5.3 Execution & Feedback Loop

    ↓

    V5.4 Self-Correction & Rule Learning

目标：

从：

    执行 + 反馈

升级为：

    执行

    ↓

    失败分析

    ↓

    修正策略

    ↓

    重新执行

    ↓

    规则沉淀

保持：

    一个人格
    一个核心意识
    一个决策中心

------------------------------------------------------------------------

# 二、工程原则

必须：

-   增量开发
-   保持 V5.3 API 兼容
-   接口优先
-   配置驱动
-   可解释
-   可测试
-   可回滚

禁止：

-   神经网络训练
-   强化学习
-   黑盒优化
-   自主修改人格
-   Agent 自由协商
-   修改 Brain/Vision/Memory Interface
-   写入 Agent Memory
-   绕过 Permission Layer
-   真实设备控制

------------------------------------------------------------------------

# 三、核心开发任务

## Task 1：Correction Engine

新增：

    backend/embodied/companion/correction.py

实现：

    Execution Failure

    ↓

    Failure Analysis

    ↓

    Correction Strategy

    ↓

    Retry Decision

新增：

    CorrectionRecord

字段：

    failure_type
    failure_source
    analysis_result
    correction_action
    retry_allowed
    created_time

------------------------------------------------------------------------

## Task 2：失败分析系统

新增：

    failure_analyzer.py

支持：

    timeout
    permission_denied
    invalid_state
    resource_unavailable
    execution_error

要求：

每种失败必须：

-   有原因
-   有处理策略
-   有日志

------------------------------------------------------------------------

## Task 3：Retry Controller

新增：

    retry_controller.py

流程：

    失败

    ↓

    判断重试

    ↓

    修正

    ↓

    再次执行

配置：

    companion_retry_max_count=2

禁止无限循环。

------------------------------------------------------------------------

## Task 4：Rule Learning Engine

新增：

    learning.py

Learning定义：

    规则统计
    +
    经验累计

记录：

    failure_pattern
    correction_success_rate
    usage_count

禁止机器学习。

------------------------------------------------------------------------

## Task 5：Executor 闭环升级

升级：

    Plan

    ↓

    Execute

    ↓

    Feedback

    ↓

    Correction

    ↓

    Retry

    ↓

    Learning

所有执行结果必须进入 Correction Layer。

------------------------------------------------------------------------

# 四、Pipeline升级

新增阶段：

    correction

    learning

最终：

    perception

    ↓

    experience

    ↓

    planning

    ↓

    execution

    ↓

    feedback

    ↓

    correction

    ↓

    learning

------------------------------------------------------------------------

# 五、配置要求

backend/config.py新增：

    companion_retry_max_count=2

    companion_correction_enabled=True

    companion_learning_enabled=True

支持：

    COMPANION_*

禁止硬编码。

------------------------------------------------------------------------

# 六、API要求

新增：

``` python
companion_correct()
```

``` python
companion_retry()
```

``` python
companion_learning_stats()
```

增强：

``` python
companion_handle()
```

保持兼容。

------------------------------------------------------------------------

# 七、测试 Prompt

新增测试：

> =100 cases

覆盖：

## Correction

-   失败分类
-   修正策略
-   Retry判断

## Retry

-   最大次数
-   成功重试
-   失败返回

## Learning

-   规则累计
-   成功率
-   数据一致性

## Integration

    Request

    ↓

    Main Companion Agent

    ↓

    Pipeline

    ↓

    Execution

    ↓

    Feedback

    ↓

    Correction

    ↓

    Retry

    ↓

    Learning

    ↓

    Response

------------------------------------------------------------------------

# 八、验收 Prompt

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

专项：

    Total >=1814
    Failed=0

全量：

    embodied
    vision
    action
    agent
    personality
    voice_identity

要求：

    Failed=0

------------------------------------------------------------------------

# 九、完成返回 Prompt

输出：

# YHLZ Embodied AI V5.4 完成报告

包含：

## 版本

    Version:
    Date:
    Commit:

## 修改文件

  文件   修改内容
  ------ ----------

## API变化

新增：

    companion_correct()

    companion_retry()

    companion_learning_stats()

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

## 自我修正指标

输出：

-   Failure分类数量
-   Correction成功率
-   Retry成功率
-   Rule数量
-   Learning统计

## 风险分析

输出：

-   已解决问题
-   已知风险
-   下一阶段建议

------------------------------------------------------------------------

# 十、最终目标

YHLZ：

    有视觉
    有声音
    有记忆
    有人格
    能感知
    能思考
    能规划
    能执行
    能反馈
    能修正
    持续进化

成为长期陪伴型 AI Agent。

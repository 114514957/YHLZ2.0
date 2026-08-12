# YHLZ Embodied AI V5.6 专业 Agent 工程 Prompt

版本： YHLZ Embodied AI V5.6

名称： Companion Relationship & Personality Stability Layer

中文： 伙伴关系与人格稳定层

------------------------------------------------------------------------

# 一、开发 Agent 角色定义

你是一名高级 AI Agent 系统架构工程师。

负责在 YHLZ Embodied AI V5.5 基础上进行 V5.6 增量开发。

演进：

    V5.5 Identity & Adaptive Personality

    ↓

    V5.6 Relationship & Personality Stability

------------------------------------------------------------------------

# 二、版本目标

V5.5 已实现：

-   PersonalityState
-   AdaptivePersonalityEngine
-   PersonalityAuditRecord
-   情境人格规则
-   互动统计

V5.6 目标：

建立：

    人格稳定

    +

    关系状态

    +

    长期互动连续性

保持：

    一个人格
    一个核心意识
    一个决策中心

------------------------------------------------------------------------

# 三、工程原则

必须：

-   增量开发
-   保持 V5.5 API 兼容
-   配置驱动
-   可解释
-   可审计
-   可测试

禁止：

-   神经网络人格
-   强化学习
-   黑盒关系模型
-   自动修改核心人格
-   保存完整聊天记录
-   写入 Agent Memory
-   多人格系统

------------------------------------------------------------------------

# 四、核心开发任务

## Task 1：人格稳定系统

新增：

    backend/embodied/companion/personality_decay.py

实现：

    当前人格状态

    ↓

    时间衰减

    ↓

    基础人格回归

新增：

    PersonalityDecayPolicy

字段：

    dimension
    base_value
    current_value
    decay_rate
    last_update

要求：

-   平滑变化
-   可解释
-   不突变

------------------------------------------------------------------------

## Task 2：时间窗口统计

新增：

    interaction_window.py

实现：

    recent_success_rate

    recent_failure_rate

    recent_interaction_count

支持：

    7天窗口
    30天窗口

禁止保存原始聊天内容。

------------------------------------------------------------------------

## Task 3：Relationship State

新增：

    relationship.py

实现：

AI 与用户关系状态。

数据：

``` json
{
"trust_level":0.5,
"communication_style":"casual",
"interaction_count":100,
"relationship_stage":"familiar"
}
```

维度：

    trust
    familiarity
    communication_style

------------------------------------------------------------------------

## Task 4：人格-关系联动

建立：

    Relationship

    ↓

    Personality Adjustment

规则：

长期稳定互动：

    trust提升
    ↓

    warmth稳定提升

连续失败：

    patience提升

要求：

规则驱动。

------------------------------------------------------------------------

## Task 5：审计升级

增强：

    PersonalityAuditRecord

增加：

    relationship_context
    decay_reason
    window_statistics

所有变化必须可追踪。

------------------------------------------------------------------------

# 五、API设计

新增：

``` python
companion_relationship()
```

返回：

-   trust_level
-   familiarity
-   communication_style
-   relationship_stage

新增：

``` python
companion_personality_stability()
```

返回：

-   当前人格
-   基础人格
-   衰减状态
-   调整历史

新增：

``` python
companion_relationship_update()
```

功能：

根据互动更新关系。

增强：

``` python
companion_handle()
```

增加：

    relationship
    personality

保持兼容。

------------------------------------------------------------------------

# 六、配置要求

新增：

    companion_personality_decay_enabled=True

    companion_relationship_enabled=True

    companion_statistics_window_days=30

    companion_decay_rate=0.05

支持：

    COMPANION_*

禁止硬编码。

------------------------------------------------------------------------

# 七、测试 Prompt

新增：

> =100 cases

目标：

    专项 >=2015
    Failed=0

覆盖：

-   Personality Stability
-   Window Statistics
-   Relationship State
-   Integration Flow

流程：

    Interaction

    ↓

    Relationship

    ↓

    Personality

    ↓

    Response

------------------------------------------------------------------------

# 八、验收 Prompt

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

专项：

    Total >=2015
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

# YHLZ Embodied AI V5.6 完成报告

包含：

## 版本信息

    Version:
    Date:
    Commit:

## 修改文件

  文件   修改内容
  ------ ----------

## API变化

新增：

    companion_relationship()

    companion_personality_stability()

    companion_relationship_update()

增强：

    companion_handle()

## 测试结果

专项：

    Total:
    Passed:
    Failed:
    Skipped:

全量：

    embodied:
    vision:
    action:
    agent:
    personality:
    voice_identity:

## 关系指标

输出：

-   trust_level
-   familiarity
-   relationship_stage
-   communication_style

## 人格稳定指标

输出：

-   decay次数
-   回归次数
-   调整次数
-   当前人格偏移量

## 风险分析

包含：

-   已解决问题
-   已知风险
-   V5.7建议

------------------------------------------------------------------------

# 十、最终目标

YHLZ：

    有视觉
    有声音
    有记忆
    有人格
    有关系

    能感知
    能思考
    能规划
    能执行
    能反馈
    能修正
    能适应

    持续进化

核心原则：

    一个人格
    一个核心意识
    一个决策中心

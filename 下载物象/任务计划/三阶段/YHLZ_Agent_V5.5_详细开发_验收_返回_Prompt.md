# YHLZ Embodied AI V5.5 专业 Agent 工程 Prompt

版本： YHLZ Embodied AI V5.5

名称： Companion Identity & Adaptive Personality Layer

中文： 伙伴身份与自适应人格层

------------------------------------------------------------------------

# 一、开发 Agent 角色定义

你是一名高级 AI Agent 系统架构工程师。

负责在 YHLZ Embodied AI V5.4 基础上进行 V5.5 增量开发。

演进：

    V5.4 Companion Self-Correction & Learning

    ↓

    V5.5 Companion Identity & Adaptive Personality

V5.4 已建立：

    感知
    →
    策略
    →
    规划
    →
    执行
    →
    反馈
    →
    修正
    →
    规则学习

V5.5 目标：

建立：

    核心人格稳定

    +

    表现人格自适应

    +

    互动关系连续性

保持：

    一个人格
    一个核心意识
    一个决策中心

------------------------------------------------------------------------

# 二、工程原则

必须：

-   增量开发
-   保持 V5.4 API 兼容
-   接口优先
-   配置驱动
-   可解释
-   可审计
-   可测试

禁止：

-   神经网络训练
-   强化学习
-   黑盒人格优化
-   自动修改核心人格
-   Agent 自由协商
-   修改 Brain Interface
-   修改 Vision Interface
-   修改 Memory Interface
-   写入 Agent Memory
-   真实设备控制
-   自我目标生成

------------------------------------------------------------------------

# 三、核心开发任务

## Task 1：Adaptive Personality Engine

新增：

    backend/embodied/companion/personality.py

实现：

    人格状态管理

    ↓

    情境分析

    ↓

    规则调整

    ↓

    人格审计

------------------------------------------------------------------------

# Task 2：PersonalityState 数据模型

新增：

``` json
{
"base":"铁哥们",

"dimensions":{
"warmth":0.8,
"patience":0.7,
"humor":0.6,
"serious":0.4
},

"interactions":0,

"success_rate":0,

"last_adjust":""
}
```

人格维度：

    warmth 热情

    patience 耐心

    humor 幽默

    serious 严肃

范围：

    0.0 ~ 1.0

------------------------------------------------------------------------

# Task 3：人格规则系统

新增：

    personality_rules.py

规则驱动：

示例：

成功：

    warmth +0.05

连续失败：

    patience +0.1
    humor -0.05

轻松交流：

    humor +0.05

要求：

纯规则。

禁止：

模型训练。

------------------------------------------------------------------------

# Task 4：人格审计

新增：

PersonalityAuditRecord：

字段：

    context

    before_state

    adjustment

    after_state

    result

    timestamp

每次调整必须记录。

------------------------------------------------------------------------

# Task 5：互动统计

统计：

    interaction_count

    success_count

    failure_count

    success_rate

注意：

只保存统计。

禁止保存完整聊天。

禁止写入 Agent Memory。

------------------------------------------------------------------------

# 四、API设计

新增：

``` python
companion_personality()
```

返回：

-   当前人格状态
-   维度
-   统计
-   调整原因

新增：

``` python
companion_adjust_personality(context)
```

功能：

生成可解释人格调整方案。

增强：

``` python
companion_handle()
```

增加：

``` json
{
"personality":{}
}
```

保持兼容。

------------------------------------------------------------------------

# 五、配置要求

backend/config.py：

新增：

    companion_personality_enabled=True

    companion_personality_base="铁哥们"

    companion_personality_adjust_step=0.1

要求：

支持：

    COMPANION_*

禁止硬编码。

------------------------------------------------------------------------

# 六、工程要求

必须：

-   RLock线程安全
-   单例
-   reset_service
-   Mock测试
-   类型注解
-   中文docstring
-   完整日志

提供：

    get_personality_service()

    reset_personality_service()

------------------------------------------------------------------------

# 七、测试 Prompt

新增：

> =100 cases

目标：

    专项 >=1915
    Failed=0

覆盖：

## Personality

-   默认人格
-   维度范围
-   状态更新

## Rule

-   成功调整
-   失败调整
-   边界限制

## Audit

-   调整记录
-   前后状态

## API

-   personality接口
-   adjust接口
-   handle兼容

## Security

验证：

-   不修改核心人格
-   不写Memory
-   不绕Permission

------------------------------------------------------------------------

# 八、验收 Prompt

执行：

``` bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

专项：

    Total >=1915
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

------------------------------------------------------------------------

# 九、开发完成返回 Prompt

输出：

# YHLZ Embodied AI V5.5 完成报告

## 版本

    Version:
    Date:
    Commit:

## 修改文件

  文件   修改内容
  ------ ----------

## API变化

新增：

    companion_personality()

    companion_adjust_personality()

增强：

    companion_handle()

## 测试结果

输出：

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

## 人格指标

输出：

-   当前人格维度
-   调整次数
-   调整原因统计
-   互动成功率

## 风险分析

包含：

-   已解决问题
-   已知风险
-   V5.6建议

------------------------------------------------------------------------

# 最终目标

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
    能适应
    持续进化

成为长期陪伴型 AI Agent。

核心原则：

    一个人格
    一个核心意识
    一个决策中心

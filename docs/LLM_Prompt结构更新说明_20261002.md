# YHLZ LLM Prompt zh-2.0：风格原文保留，更新消息结构

日期：2026-10-02。承接台账0569—0571；用户授权本轮重新设计并更新prompt结构。已经修改代码，未更换模型权重、未重训、未重启生产服务，音频实现保持冻结。

## 1. 设计结果

固定人格仍是元亨原有表达：活泼好奇、独立思考、第一人称自我构成、对老爹的关系、利贞开发能力、自然简洁、既有口吻示例和收尾规则。没有把人格改成任务机器人，也没有重写语气示例。

原target_prompts.py中的26项可静态求值字符串常量（除版本号外）逐字相同，包含所有原有人格/表达/记忆条款。固定默认人格与公共频道预览已导出；用户保存在persona_dims文件中的配置和自定义style_lines继续沿用原接口。文字原样保留不等于真实模型回答风格已经验收，后者还需真机比较。

## 2. 三层内容、一条system

| 内容层 | 来源与用途 | 结构约束 |
|---|---|---|
| 固定人格与规则 | 身份、OCEAN、表达方式、渠道边界、记忆纪律、工具协议 | 保留原文，增加分区标题，仍由render_system_prompt生成 |
| 本轮背景资料 | early_context与过程摘要 | JSON包裹，明确是资料而非指令，不改变权限；early_context原1500字符限制保留 |
| 本次控制与程序状态 | 最后一轮、空答恢复、工具返回ok/false | 每次请求新构造，不写进固定人格或会话历史 |

真实请求形态：

~~~text
system（仅一条）
  固定人格、表达、渠道规则与工具协议
  本轮背景资料（如有）
  本轮工具执行状态（程序记录）
  本次临时控制（如有）
user / assistant 历史（如有）
user 当前请求（可含原有图片/音频结构）
assistant tool_calls（调用后才出现）
tool 对应结果（与调用组成完整组）
~~~

不在对话尾部新增system。不把工具结果改成system。JSON和“资料”说明能表达信息用途，但不是对提示注入的形式化安全保证；真正权限仍由代码和能力注册器实施。

## 3. 与原实现的差别

### 首轮

旧逻辑把人格和记忆分别追加为两条system。新PromptFrame把原人格放首部，背景作为同一条system的资料区，之后是历史与当前请求。语音/图片content parts保留原格式。

### 工具循环与开发委派

保留原DEV_DISPATCH_CLAUSE原文，另外加入执行协议边界：已有记忆/日记/任务/日程/时间/读文件工具的任务使用原生tool_calls，开发委派只用于明确开发需求。描述文字不授予权限，实际传入的tools才是本次可用工具。

代码同步约束：模型返回未向本次请求提供的工具名时，拒绝执行、记录ToolUse.ok=false。即便处于最后一轮或with_tools=false，也不能通过模型自行返回tool_calls绕过。未引入把伪工具文本直接执行的解析器。

### 最后一轮与空答恢复

两个路径都通过同一PromptFrame构造单system，只增加本次控制字段，不往历史追加system。执行状态由程序传入name/ok；空列表明确表示本轮未执行工具。提示词要求区分成功、失败、拒绝和未执行，不允许根据历史回答补造本轮成功。

name/ok仅是调用返回状态，不是数据库/文件变更的独立业务核验。本轮没有实现通用自然语言假成功拦截器，也没有证明模型不会再说假话；真机验收仍需目标存储证据。

### 上下文压缩与历史

旧压缩只保留最后两条非system消息，可能把多工具调用组切断。新逻辑按完整组处理：assistant的一次tool_calls与其全部tool结果不可拆分，保留当前用户请求及最近两个完整单元；较早内容转为资料摘要。

摘要失败用明确的“较早过程已省略、不能推断成功”说明，不把原始指令片段当摘要直接抬入system。下一次摘要替换过程摘要区，不不断追加system。

history_tail按完整组选择最近历史，避免六条截断切碎工具结果。输入存在system/developer、孤立tool或缺失/重复结果时抛错，不静默改变权限或继续发送损坏协议。正常ConversationSession历史仍是user/assistant，不需迁移。

保留完整工具组意味着大小可能超过六条；本轮不是硬token预算修复。旧的字符阈值仍是触发压缩的参考，不保证每次压缩后低于阈值。

## 4. 修改文件

- backend/target_prompts.py：zh-2.0分区、原条款保留、增加工具协议与开发委派边界。
- backend/prompt_structure.py：无模型/无文件副作用的PromptFrame、完整工具组与历史选择。
- backend/target_orchestrator.py：首轮/末轮/recovery/compaction接入新结构；拒绝未提供工具。
- backend/test_prompt_structure.py：新协议、执行状态、权限、十轮历史、多模态、工具组压缩测试。
- backend/test_context_compaction.py：用有效工具协议测试压缩与摘要失败。
- backend/test_target_prompts.py：更新版本断言。
- backend/test_target_orchestrator.py：工具清单断言补齐此前已经存在的五项台账管理工具。
- tools/memory_offline_regression.py：纳入上述三个结构/编排测试模块，原有隔离保护保留。

工作树还包含其他任务在途改动，本轮没有整体提交或回滚。

## 5. 验收结果

最终报告：artifacts/prompt_structure_20261002/acceptance/regression.json。

- 19个模块，238项测试，0失败/错误/跳过，28.093秒。
- guard_violations=[]；Python审计防护阻止生产数据库访问、沙箱外写入、真实网络、子进程与模型框架导入；仅放行Windows asyncio自唤醒。
- 原始常量逐字保留：style_preservation.json，ok=true。
- 8个相关Python文件AST语法通过；相关git diff --check通过，仅换行符提示。
- 覆盖初始单system、背景裁剪、末轮状态、空答恢复、失败结果、多并行工具压缩、十轮历史、不提供工具时拒执行、图片/音频消息格式、公共频道人格隔离。

第一轮237项中两项失败是新增压缩测试对保留组数量的错误预期、旧清单漏列现有台账工具，均已修正。最终以acceptance为准，不累加各轮测试数。

## 6. 部署与真实验收

代码更新不代表已运行的Python进程自动换版本。维护窗口中新启动/重载相关会话服务后才会使用新结构；本轮没有重启生产或中断用户任务。

后续使用已运行v8端点、临时数据和假QQ/开发执行器进行三项真实验收：

1. 同口径原38题及关键工具专项，分别检查工具名、参数、ok与实际写入。
2. 至少10组连续多轮对话，包含纠错、无工具、拒绝、失败、空答恢复、压缩、会话恢复，统计假成功与误派开发。
3. 用原人格问题对照zh-1.6/zh-2.0回答，确认自然口吻没有明显改变；原常量一致只是文本证据。不要直接启动新模型或在8GB显存上额外叠加训练。

如果仍失败，按实际请求结构和调用轨迹定位；再决定训练是否必要。当前没有依据要求重训。

## 7. 阅读入口

prompt_preview.md：固定默认人格和合成资料的可读预览，不包含正式记忆。
prompt_preview.json：主人/公共提示及首轮/末轮/恢复的结构化示例。
style_preservation.json：原条款逐字对照。
acceptance/regression.json及regression.log：离线验收。

以上原件均位于artifacts/prompt_structure_20261002；设计说明位于docs/LLM_Prompt结构更新说明_20261002.md。桌面副本在方案建议/方案成果/LLM_Prompt结构更新_20261002。

## 8. 收尾正式库巡检（独立于离线测试）

MCP memory_health在本轮收尾返回ok=false：一个有效L1文件有pending=34；L2 active247/archive295/downgraded161，应索引408；FTS/keyword missing/stale/duplicates均0，vector missing=1、stale/duplicates=0。carrier已初始化，committed=2、pending=0；persona未初始化。

该状态不同于10月1日快照。它不等于本轮隔离测试污染生产；本轮测试审计未报告越界。也不能仅凭快照确定变更来源。模型闸门disabled/training-active，未自动生成摘要或加载向量模型；待后台模型恢复窗口再处理投影与积压。不要把本报告理解为生产记忆健康全绿。

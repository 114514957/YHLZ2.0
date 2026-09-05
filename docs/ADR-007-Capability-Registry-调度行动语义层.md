# ADR-007：Capability Registry + 调度器（行动语义层）

- 日期：2026-09-03
- 状态：Draft（今晚循环开发定稿）
- 关联：ADR-006（六边形收敛）、文档 0138/0144/0145、旧项目建议（能力注册表+Router+Event Bus+State Machine）

## 1. 背景与问题

YHLZ 已拥有大量独立组件层：宪章（constitution）、智能层（llm_reasoner/hybrid）、工具（agent ToolRegistry/Executor）、记忆（target_memory）、治理（action/permission、记忆三不变量）、状态机（TargetVoiceRuntime RuntimeState）、事件检验（verification）。**问题不在组件数量，而在缺少统一的行动语义与调用入口**：系统不知道该在何时调用谁、以何顺序、结果交给谁——组件齐、调用不起来（"做了一堆摆着当花瓶"）。

旧项目经验：函数阵列解决"能力怎么暴露"；还必须解决"当前发生了什么→需要什么能力→哪几个满足条件→谁先执行→结果是否可信→下一步干什么"。

## 2. 边界（核心设计区分）

**第一类——能力（Capability）**：视觉/听觉/记忆/模型/工具/状态等可被决策者选择的东西 → 进 **Capability Registry**（能力白名单，模型只能调用注册表内能力）。
**第二类——控制机制（Control Plane）**：宪章约束/治理/权限/状态机/事件检验 → **绝不作为普通能力注册**，而是包在调用链外层（gate/policy），**不可绕过、不可被模型"决定是否遵守"**（fail-closed：policy 未注册 → 拒绝执行）。

## 3. 行动语义管线

```
Event（事件/请求流；turn observer + 系统事件=已有）
   ↓
Orchestrator（总调度：LLM 自主决策 = llm_reasoner tool_choice + prompts 工具描述）
   ↓
Capability Registry（元数据 + 白名单；模型只能看到这里导出的能力）
   ↓ 前置 Gate
Control Plane（policy checks：宪章/权限/风险审批位 → 未注册=拒绝；fail-closed）
   ↓
Execute（handler；side_effect / timeout / 元数据）
   ↓
Verify（事件检验：结果是否为真——如 TTS TailVerifier / 工具结果真实性）
   ↓
Commit（状态更新：TargetVoiceRuntime RuntimeState / 记忆只留下已确认事件）
   ↓
Output（表现层）
```

**管线原则**：
1. 能力必须带元数据（见 §4），调度器据此决定"现在调用谁/能否调用/失败回滚"。
2. 政策未注册 → 默认拒绝（安全默认），禁止存在"未开天窗"的能力。
3. 执行结果必须回写事件（Event Bus），供下一轮状态与心智使用。
4. 记忆/持久化只对被 Verify 确认的事实提交（提交语义：先审后存）。

## 4. Capability 元数据（定稿）

```python
@dataclass(frozen=True, slots=True)
class Capability:
    name: str                 # 点分命名: ledger.search / memory.recall / system.time
    handler: Callable[[dict], Any]
    input: tuple[str, ...]            # 必填入参名
    optional_input: tuple[str, ...]   # 可选入参名（缺省由 handler 处理）
    requires: tuple[str, ...]         # 控制面 policy ids（未知/被拒 => 拒绝执行）
    side_effect: bool                 # 是否写状态
    risk: str                         # low|medium|high（high=必须显式审批 policy，否则构造即拒绝）
    timeout_ms: int                   # 执行超时（默认 4000）
    priority: int                     # 同轮并发时的执行序（默认 50）
    rollback: Optional[Callable]      # 失败回滚（写入类必配）
    verify: Optional[Callable]        # 结果真实性校验；失败=>ok=False+rollback（Verify 步）
```

**增补（0147 循环开发）**：
- **审批位**：`risk="high"` 的能力在构造时强制 `requires` 非空且含审批 policy（如 `*.approval`），否则拒绝注册（fail-closed；模型无法绕过）。
- **Verify 步**：verify(out) 返回 truthy 才算可信；falsy=结果不可信 → ok=False + rollback（与 ADR-007 管线 "结果是否为真" 对齐；如 TTS TailVerifier/工具输出模式校验）。
- **Commit 钩子**：注册 `set_commit_hook(cb)`，每次成功执行回填 Event Bus（系统事件），供"状态机提交位/表现层"使用；注册表本身不持有状态。

**命名双面**：内部点分 `domain.verb`；OpenAI 暴露面下划线 `domain_verb`（DeepSeek/OpenAI 工具名规范 `^[a-zA-Z0-9_-]+$`，0146 实测）。

**命名**：`领域.动词`（如 ledger.search、memory.recall、system.time、model.compose、audio.output）。与 Agent-Core 旧 ToolRegistry 兼容（export_openai_tools）但执行只走 Registry（ToolRegistry 仅作 LLM 工具视图/后端兼容）。

## 5. 首期范围（今晚）

1. `backend/target_capability_registry.py`：Capability/CapabilityRegistry（register/register_policy/can_execute/execute/export_openai_tools）。
2. `backend/target_scheduler_tools.py`（重写干净版）：3 个只读调度能力 ledger.search/memory.recall/system.time + 政策 `scheduler_allowed`（默认放行，作桥接）。TargetMemoryService.recall 只读尊重三不变量。
3. 单测 `backend/test_target_capability_registry.py`（gate 拒绝/未知政策 fail-closed/缺失入参/超时/回滚/导出白名单/政策绝不导出）+ 调度工具集合同步覆盖。
4. 批2（非今晚）：Orchestrator 入链（chain turn 挂 hook）、high-risk 权限位接线（action/permission）、Verify 策略（工具结果真实性）、状态机提交位。

## 6. 非目标（明确不做，防花瓶反弹）

- 不做"模型可调用宪章/治理"类能力（控制面永不导出）。
- 不做注册表自动扫描（能力必须显式注册+测试证言）。
- 不做 session 内持久化注册表（运行时组装，无持久状态）。

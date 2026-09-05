# ADR-006: 目标语音链路六边形架构收敛（Hexagonal / Ports & Adapters）

状态：采纳，与 ADR-001（Session Kernel）配套，渐进实施。
时间：2026-09-02（Asia/Shanghai），依据台账记录 0001/0011/0091/0092/0108 与用户确认（“Port-Adapter 模式彻底进化成六边形架构”）。

## 背景

YHLZ 现状（台账 0001/0013）：`backend/main.py` 直接持有多组全局 ASR/TTS/VAD 引擎与两套会话/回合管理；入口、WebUI、Avatar、Demo 边界混杂。目标链路（ADR-002）已用“能力模块化单体 + Session Kernel + Provider Port/Adapter + 组合根”收敛，实际已是六边形架构的雏形，但尚未固定为明示的分层规则，避免新代码重新从内核直接依赖外部 SDK/进程。

## 决策

目标语音链路按“六边形架构”明示分层，依赖方向一律指向内核：

```text
                驱动方适配器 (Driving Adapters)
  start.bat/编排器 │ WebUI/HTTP-WS 兼容门面 │ probe 工具入口
 ──────────────────┴──────────────────────────────┐
           │           驱动方端口 (Driving Ports)          │
           │    提交 turn / 停止 / 事件订阅 / 健康查询       │
 ──────────┴──────────────────────────────┐
        ┌─────────────────────────────────▼──────────────────────┐
        │                      内核（Domain）                      │
        │  SessionKernel（session/turn/generation/取消代际）        │
        │  TargetVoiceChain（链路状态机、唤醒门、“元亨”）          │
        │  Runtime 编排（media→asr→reasoner→tts→playback 顺序）    │
        │  Memory 只读门面（MemoryFacade，写操作 fail-closed）     │
        └─────────────────────────────────┬──────────────────────┘
 ──────────┼──────────────────────────────┘
           │           被驱动方端口 (Driven Ports)
           │  TTSProviderPort / StreamingASRProviderPort /
           │  LLMProviderPort / 播放端口(输入源/输出源) /
           │  VAD/AEC Provider Port / Memory Port
 ──────────┴──────────────────────────────┐
                被驱动方适配器 (Driven Adapters)
  Qwen TTS 子进程 │ Sherpa-onnx │ vLLM(HTTP) │ sounddevice 输入/输出
  Silero ONNX │ RNNoise/AEC(外围可选) │ SQLite/文件只读门面
```

规则：
1. **依赖只向内**：内核不导入任何 Provider SDK/网络/设备库；适配器只实现端口，不修改内核状态。
2. **端口即契约**：每个端口必须有版本号、能力声明（与运行时证据分离）、稳定错误码、停止/等待证据方法与脱敏元数据（Payload 只保留计数/哈希/时延，不保存文本/音频/转写）。
3. **组装根唯一**：`TargetVoiceComposition` 继续是唯一组合根；再上层只允许“驱动方适配器”引用它。禁止在路由层再组合 Provider。
4. **能力不虚报**：适配器声明的 streaming/cancel/close 能力属于“候选”，必须由真实探针验证后才允许固化到 READY 语义（记录 0041/0058）。
5. **外围隔离**：AEC/RNNoise、Edge 回退、WebUI、Avatar、视觉等只通过各自端口/适配器接入，不进入内核。
6. **渐进迁移**：旧 `backend/main.py` 路由仍作为“兼容门面”（可观察、可废弃），不直接调用 Provider 全局对象新建第二套状态（记录 0011/0015）。

## 演化路径

1. （进行中）按此规则新增 `LLMProviderPort` + vLLM 适配器 + Reasoner 适配器（本 ADR 首件落位）。
2. 目标链路的入站驱动方端口（turn 提交/事件订阅/健康）收敛到 Session-Kernel-Protocol（ADR-001），兼容门面代理。
3. 未来入口（start.bat 编排器）作为驱动方适配器启动组装根；核心失败阻止 READY（0108：LLM=核心）。
4. 迁移旧代码时只收容不进内核：旧全局引擎停用时按“搅杀式”退役（台账 0001）。

## 边界

- 六边形架构只约束**目标语音链路**；`backend` 既有业务域（Agent/Vision/Embodied 等）暂按外围适配器视图处理，等各自边界收敛后再逐域对齐。
- 不引入新框架/DI 容器；组合根仍用普通工厂函数。
- Memory 数据、声音缓存、历史业务数据不受影响；写入口仍只允许经只读门面（记录 0010）。

## Agent 演进接入点（触发器：Agent 接入时评审）

用户已宣布未来将把 Agent 等复杂结构加入 YHLZ；本 ADR 只定义接入点与升级条件，不在接入前预先实现 Agent 结构。

### 形态定位

- **Agent = 驱动方服务（Driving Service）**：Agent 作为“交互协调器”运行在内核之外（reasoner 之上/外层），不写入内核，不持有第二套 turn/取消真值。
- **演进缝（已预留，Port 1.1）**：`LLMProviderPort.stream_chat` 支持可选 `tools/tool_choice`（OpenAI shape 透传）；`LLMReasoner` 可被子类化（`AgentReasoner`）走工具循环，`generate(text, signal)` 契约不变，`TargetVoiceChain` 不修改；工具执行作为 **driven port（ToolPort 候选）** 由外围适配器实现，不进内核。
- **记忆形态（四层，Agent 接入时确定最终注入与召回方式）**：
  1. 固定模板：`先进始于计算，元亨开拓未来`（system 固定）；
  2. 用户/项目准绳：根 `memory/` 三个 Markdown（只读门面）；
  3. **项目经验记忆：上下文台账**（`docs/上下文台账.md`，追加式、只读事实源；经 `docs/ledger_search.py` 检索定位；未来可重建 FTS5 索引——记录 0094 预留。Agent 期以**工具型召回**接入（主动查询），不自动注入对话，不与业务记忆力/人格记忆混同）；
  4. 会话内缓冲：Reasoner 内部有界环（接入时评审实现）。
- **远期参考**：NEKO 五层记忆（近期/事实/反思/人格）与混合召回（BM25+余弦+时间），按接入时评审决定是否演进 YHLZ 长期记忆层。
- **升级到整洁架构的触发条件**：Agent 接入时评审一次；若出现 ≥2 个独立驱动方用例或工具编排横跨 ≥3 域，则仅在对应域内引入用例层（域内六边形/洋葱），不做全局重写。
- **禁止点**：Agent 不得直接把工具调用写进内核状态；不得把业务记忆/对话正文写入台账；台账永不改写历史（只追加）。

# YHLZ 项目改进技术报告 v1

- 日期：2026-09-14（Asia/Shanghai）
- 作者：元亨（YHLZ 开发执行体，opencode CLI / deepseek-v4-flash / agent `yhlz-dev`）
- 性质：知识汇总 + 主题映射 + 分级改进建议（**只读分析产出，不含代码改动**）
- 关联：ADR-001~007、`docs/YHLZ_记忆架构_设计_v2.md`、`docs/上下文台账.md`

---

## 0. 范围、来源与诚实条款

### 0.1 输入源

| 代号 | 文件 | 用途 |
|---|---|---|
| [S1] | `docs/知识汇编/QQ-主题总结-2026-09-06.md` | 主知识源（127 条 → 8 主题） |
| [S2] | `docs/报告/QQ技术周报_2026-09-10.md` | 主题式周报（增量/补充） |
| [S3] | `docs/技能库/QQ知识捕获工作流.md`、`docs/技能库/数据口径与格式.md` | 两条已批技能（SOP + 口径） |
| [P] | `docs/ADR-001~007`、`docs/YHLZ2.0_VoiceIdentitySystem_架构设计白皮书.md`、`docs/Session-Kernel-Protocol-v1_草案.md`、`docs/YHLZ_记忆架构_设计_v2.md` | 项目侧映射基准 |
| [C] | `backend/` 模块清单与源码（2026-09-14 盘点） | 判定"已体现/缺口"的实证 |

### 0.2 诚实条款

- 知识库 `kb_query` 接口当前 **verify failed**；本报告知识点一律从 [S1]/[S2] 文件读取，**未使用接口、未编造条目**。
- `docs/知识汇编/QQ-2026-09-07/08/09/13.md` 为占位残片（重复单条 llama.cpp / 一句口径提醒），不含新知识，未纳入。
- "已体现"判定基于源码/文档现状盘点；**未做真机验证**的能力（尤其全双工 C、AEC、视觉）一律标注为"未验证"，不以链路状态代替证据（遵守 `docs/技能库/数据口径与格式.md` 诚实条款）。
- 本报告为 v1 分析稿，**不修改任何实现**；后续落地需按台账循环：先设计 → 改 → 单测 → 真机 → 快照。

### 0.3 知识底座

全量知识点已单独归集到 `下载物象/QQ技术知识总汇-8主题-2026-09-14.md`（8 主题、约 48 条含启发）。本报告第 1 节为其摘要索引。

---

## 1. 到现在所有知识点（按 8 主题归类，标注来源）

> 完整条目见 `下载物象/QQ技术知识总汇-8主题-2026-09-14.md`；此处给出主题与关键点索引。

| 主题 | 关键知识点（摘要） | 来源 |
|---|---|---|
| **1 Agent 记忆与人格设计** | 记忆四层分层（原始/事实/记忆网-图RAG/核心）；短时窗口按运行时间淘汰、可持久化；人设渐进剥离；记忆=对当前状态的持续影响；从最终提示词反向设计记忆；贝叶斯主动引导 + 三层记忆；世界模型是内在表征 | [S1][S2] |
| **2 Agent 架构与多 Agent 协作** | 长期目标+任务队列+工具规划+结果认证+失败恢复；多 Agent 松耦合、子代理自行交接；主 Agent 路由需防上下文爆炸、固定对话绑定单一 Agent；能力注册表+调度器替代 if/else；难题直接重构；Surface/Tunnel 分层 | [S1][S2] |
| **3 推理部署与工程实践** | llama.cpp 并发 prefill 提升 100x、cache hit 毫秒级、兼容性优于 vLLM；本地需量化、AMD 矿卡可行；SM70/75 停支持；报错先 Retry 再新会话；成本大头在上下文缓存读取；关注 role/分块；软硬件栈匹配 | [S1][S2] |
| **4 语音交互与多模态** | 良好体验需全双工（本地难）；流式争取时间 + 整句合成；上下文 6 轮以上并压缩、浏览器 AEC、提示词先出短句降延迟；多模态输入/输出需专门训练；视觉需接入模型 | [S1] |
| **5 模型架构与稀疏化** | FFN 隐式专家分工、单层稀疏化有效；大规模稀疏化层间退化、恢复开销大；固定结构化 SVD 转 MoE 达 84%；仅 pipeline 难端到端；抹平脑样结构致能力下降；降 20% PPL/跳 40% 计算 | [S1][S2] |
| **6 学习机制与世界模型** | 持续学习三路径（工具箱/上下文注入/改源模型）；广义持续学习=策略层；世界模型≠视频生成；JEPA/预测编码潜空间预测；须区分模拟与现实（Minecraft 非真 world model）；AI 知识广度超个体但"通晓全部"伪命题 | [S1][S2] |
| **7 工具集成与安全设计** | 不可逆操作留人工确认、权限可随时收回、权限层独立于自修改能力；危险操作拦截；NapCat 桥接层消费消息；`send_poke` 戳一戳；桌宠=API+检索记忆+工具多模态 | [S1] |
| **8 开发方法与成本优化** | 规格→AI 出码→验收，把 AI 当编译器；设计文档不做可执行代码、层分离（公式引擎用代码、LLM 管语言）；ReAct 先循环再配工具；基于开源二次开发（opencode/pi）；成本是核心瓶颈 | [S1][S2] |

---

## 2. 逐主题"对 YHLZ 项目的映射"

图例：**✅ 已体现** ／ **⚠️ 缺口** ／ **➡️ 可直接吸收**

### 主题 1　Agent 记忆与人格设计

- ✅ **分层记忆**：`backend/target_memory.py` 已实现 L0 上下文(`history[-6:]`) / L1 工作(`_turns`+`_summary`，持久化 `<db>.l1.json`) / L2 长期(`l2_items`+FTS5/BM25+belief/salience) / L3 认知人格(`docs/元亨认知根基.md`+`memory/*.md`+`persona_dims.json`)。
- ✅ **图 RAG / 记忆网**：`backend/entity_graph.py`(三元组) + `backend/associations.py`(PPR 激活扩散，HippoRAG 式) + `backend/communities.py`(Louvain 社区摘要)。
- ✅ **人格渐进 / 巩固**：`backend/reflection.py`(反思→PENDING 候选) + `backend/target_persona_loop.py`(consolidate → 认知根基)，呼应"人设渐进剥离、记忆引导行为"。
- ✅ **记忆写保护**：`backend/memory_guard.py` 的 `ReadOnlyMemoryFacade`（写操作 fail-closed）。
- ⚠️ **Profile/Episodic 未显式分层**：`docs/YHLZ_记忆架构_设计_v2.md` 的 M1（`kind`/`protected`）尚未落地，L2 仍混一表。
- ⚠️ **证据/冲突未升级**：仍单标量单时钟；`backend/memory_judge.py`(legacy 规则) 未退役，`backend/memory_adjudicate.py`(证据裁决) 已建但 M2 未定稿。
- ⚠️ **检索无真 RRF**：`target_memory.py` 自述 "RRF-ish"（关键词+向量+BM25 分数合并 + rerank），非严格 RRF；无自动注入/工具召回双路径分离门槛。
- ⚠️ **管理闭环缺失**：后台任务多处 fire-and-forget，无游标/事件日志/预算熔断。
- ⚠️ **无梦境/联想沉淀引擎**。
- ➡️ 吸收 **1.5**（从最终提示词反向设计记忆）到 `target_prompts.render_system_prompt` 的注入策略；吸收 **1.2**（按运行时间淘汰）对齐 L1 有界窗口。

### 主题 2　Agent 架构与多 Agent 协作

- ✅ **能力注册表 + 调度器**（本主题最核心的落地）：ADR-007 + `backend/target_capability_registry.py` + `backend/target_orchestrator.py`(ReAct-lite 工具循环) + `backend/target_scheduler_tools.py`。注册表白名单、政策 fail-closed、控制面政策永不导出给模型。
- ✅ **上下文爆炸防护（半）**：`target_orchestrator.py:25` `CTX_BUDGET_CHARS=16000` + `_compact()` 中途压缩。
- ⚠️ **多 Agent / 子代理交接未实现**：全仓无 `subagent`/`handoff`；仅单 Agent（`TurnOrchestrator`；`backend/agent/` 为单 ReAct，且仅测试/遗留引用）。
- ⚠️ **两条 turn 路径割裂**：能力注册表/调度器/安全门只在 daemon 路径（`target_entry.py`）；**目标语音链**（`target_composition`→`target_chain`→`target_runtime`）不 import 注册表，直接 `reasoner.generate`，无工具循环。
- ⚠️ **Surface/Tunnel 分层未落地**。
- ➡️ 吸收 **2.3**（固定对话绑定单一 Agent）作为多 Agent 前置约束；**2.5**（难题直接重构）与现有"渐进迁移/搅杀式退役"一致；**2.6** 分层纠错作为 P2 评估。

### 主题 3　推理部署与工程实践

- ✅ **API 主 + 本地兜底**：`backend/llm_hybrid_provider.py`(sticky、双方都挂才 fail-closed) + `backend/llm_hybrid_compose.py`(DeepSeek 主 + Ollama 备)。
- ✅ **llama.cpp 作为外部 HTTP**：`target_orchestrator.py:128`、`target_daemon.py:449`；GGUF 资产路径在 `backend/yhlz_paths.py:33-34`(`GEMMA_GGUF`/`MMPROJ_GGUF`)。
- ✅ **legacy token 计数/响应缓存**：`backend/context_manager.py`(tiktoken) + `backend/llm_engine.py`(响应缓存命中统计)。
- ✅ **成本阈值配置**：`backend/config.py` `companion_hybrid_high_cost_threshold`。
- ⚠️ **无 LLM prompt-cache 命中率/成本追踪**：无 `cache_hit`/`prompt_cache` 指标（`_prompt_cache` 仅 TTS 声音克隆）；成本优化无量化。
- ⚠️ **无并发 prefill 优化 / 量化落地**：量化仅训练侧 `tools/finetune_train.py`(bitsandbytes 4-bit)。
- ➡️ 吸收 **3.5**（成本聚焦缓存命中率）→ 建议加指标；**3.4**（先 Retry 再新会话）→ 写入运维 SOP。

### 主题 4　语音交互与多模态

- ✅ **全双工边界与取消**：`backend/session_kernel.py`(`DuplexMode.C/B`、`abort_active_turn`、`EventJournal` 迟到事件)；`backend/target_chain.py:598 interrupt`(区分 barge-in)；`backend/target_playback.py:211 interrupt` + 24kHz 有界队列/预缓冲。
- ✅ **流式 ASR**：`backend/streaming_asr_bridge.py`（partial 不落地、仅 final 入链）+ `backend/target_vad.py`(Silero ONNX，资产校验)。
- ✅ **验收模型**：`backend/target_runtime.py` `FullDuplexAcceptance`（默认 `not_run`）+ `backend/target_acceptance.py`。
- ✅ **上下文压缩**：`history[-6:]` + 滚动摘要，方向与"6 轮以上并压缩"一致。
- ⚠️ **全双工 C 未真机验证**：默认 `not_run`，无真机证据；不得以清队列/模拟 fallback 宣称取消成功。
- ⚠️ **AEC 未进目标链**：`backend/echo_cancellation.py` 存在但 `target_composition` 未接线；`noise_suppression.py` 为 legacy。
- ⚠️ **视觉输入未接入**：项目有视觉域但不在目标语音链，模型本身不支持视觉。
- ➡️ 吸收 **4.2**（流式争取时间 + 整句合成，已有基础）；**4.3** 浏览器 AEC → 评估本地 `echo_cancellation` 作为替代；**4.5** 多模态走工具调用而非模型内建。

### 主题 5　模型架构与稀疏化

- ⚠️ **项目无对应实现**（无稀疏化/MoE/SVD 相关代码）。
- ➡️ **非近期范围**：建议作为 P2 观察项建立跟踪，不投入实现资源。

### 主题 6　学习机制与世界模型

- ✅ **持续学习走"策略层不改权重"**：`reflection.py`/`target_persona_loop.py`/`intrinsic_drives.py`；记忆架构 v2 明确"不训参数"铁律。
- ✅ **世界模型内在表征/区分模拟与现实**：理念与项目"数字生命/认知根基"一致，但无技术实现。
- ⚠️ **无 JEPA/预测编码、无 world model**。
- ➡️ 吸收 **6.1**（工具箱/上下文注入两条路径，本项目正走此路）；**6.4** JEPA 作为长期观察。

### 主题 7　工具集成与安全设计

- ✅ **fail-closed 安全门**：`target_capability_registry.py` `can_execute`（缺政策即拒、政策异常即拒；`register_policy` 永不导出）；`target_constitution.py:31 check_text`（确定性、模型不可绕过）；`target_access.py`（敏感/二进制拒读 + untrusted 标记）；`memory_guard.py` 写 fail-closed。
- ✅ **人工审批**：`grant_policy_once` + `*.approval` 政策；`target_scheduler_tools.py` 为 `memory.save.approval`/`diary.delete.approval` 注册 deny-all 默认。
- ✅ **QQ 桥接层**：`backend/qqwatcher.py`(静默 OneBot 捕获) + `backend/qq_outbox.py`(主动消息队列) + NapCat（技能 [S3]）。
- ⚠️ **安全门未覆盖目标语音链**：与主题 2 同一"两条路径"问题。
- ⚠️ **权限层独立于自修改能力**：设计有，自修改能力尚未实现。
- ⚠️ **无 NapCat `send_poke` 实现**。
- ➡️ 吸收 **7.1**（不可逆操作人工确认/权限可收回，已部分）；**7.2**（危险操作拦截，已有）；**7.3**（桥接层消费 NapCat，已有）。

### 主题 8　开发方法与成本优化

- ✅ **规格→出码→验收**：本项目工作流 + `backend/target_acceptance.py` 机器可读验收 + probe 系列。
- ✅ **层分离**：`target_constitution.py` 把"规则/判定"用确定性代码实现，LLM 只做语言理解——正是"公式引擎用代码、LLM 管语言"。
- ✅ **ReAct 先循环再工具**：`target_orchestrator.py`。
- ✅ **基于开源二次开发**：本项目基于 opencode CLI 运行（agent `yhlz-dev`）。
- ⚠️ **成本无量化闭环**：缺 token/cost 预算与缓存命中指标（同主题 3）。
- ➡️ 吸收 **8.5**（成本是核心瓶颈）→ 提升为 P1 可度量项。

### 映射总览

| 主题 | 已体现 | 缺口 | 可直接吸收 |
|---|---|---|---|
| 1 记忆人格 | 高 | 中（M1~M5 未落地） | 1.2 / 1.5 |
| 2 Agent 架构 | 中高 | 高（多 Agent、双路径） | 2.3 / 2.5 / 2.6 |
| 3 推理部署 | 中 | 中（成本/量化指标） | 3.4 / 3.5 |
| 4 语音多模态 | 中高 | 中高（C 未验证、AEC、视觉） | 4.2 / 4.3 / 4.5 |
| 5 稀疏化 | 无 | —（范围外） | 观察 |
| 6 学习世界模型 | 低 | 高（无实现） | 6.1 / 6.4 |
| 7 工具安全 | 高 | 中（未覆盖语音链） | 7.1 / 7.2 / 7.3 |
| 8 开发成本 | 高 | 中（成本量化） | 8.5 |

---

## 3. 分优先级改进建议（P0/P1/P2）

> 每条注明：**依据知识点** ／ **涉及项目模块** ／ **验收信号**。
> 落地纪律沿用台账循环：先设计+台账 → 改 → 单测 → 真机 → 快照；不做"半接线"。

### P0（运行时约束与安全底线，先做）

**P0-1　打通两条 turn 路径，让目标语音链也走能力注册表 + 安全门**
- 依据：2.4（注册表+调度器）、7.1/7.2（安全护栏）、2.6（分层）
- 模块：`target_composition.py`、`target_chain.py`、`target_runtime.py`、`target_orchestrator.py`、`target_capability_registry.py`、`target_constitution.py`
- 验收：语音链 turn 的工具调用经 `can_execute` fail-closed；控制面政策不出现在导出工具集；现有 `test_target_chain`/`test_session_kernel` 全绿 + 新增接线测试。

**P0-2　记忆写防火墙全覆盖 + 不可逆操作人工确认**
- 依据：1.4（记忆=持续影响，须防污染）、7.1（不可逆操作留确认）、7.2（危险操作拦截）
- 模块：`memory_guard.py`、`target_scheduler_tools.py`、`target_access.py`、`target_memory.py`
- 验收：任何写路径 fail-closed；高危能力必须带审批政策；审批/拒绝留痕可审计；`test_target_constitution`/`test_target_scheduler_tools` 全绿。

**P0-3　全双工/取消/迟到事件终态的真机验证（只认证据）**
- 依据：4.1（全双工难）、4.3（延迟/打断）、1.2（有界窗口）
- 模块：`session_kernel.py`、`target_runtime.py`、`target_acceptance.py`、`target_playback.py`
- 验收：真机 C 认证须有可核验证据（设备/Provider 实测）；否则报告"未认证"，禁止用清队列或模拟 fallback 代替取消成功（对齐台账既有结论）。

### P1（能力补齐与可度量）

**P1-1　记忆 v2 M1：Profile/Episodic 显式分层 + protected 免衰减**
- 依据：1.1（分层）、1.3（人格渐进）
- 模块：`target_memory.py`
- 验收：单测+真机 Profile 精确命中、protected 不衰减/不被清扫。

**P1-2　统一证据裁决器 + 双时钟，退役 `memory_judge`**
- 依据：1.4（记忆改写与冲突）
- 模块：`memory_adjudicate.py`、`memory_judge.py`、`target_memory.py`
- 验收：裁决样例集准确率；不确定→问老爹；裁决留痕（supersede/rejected）。

**P1-3　检索闭环：RRF 融合 + 自动注入/工具召回双路径分离**
- 依据：1.1（记忆网检索）、3.5（成本/上下文）、8.5（成本瓶颈）
- 模块：`target_memory.py`(`contextual_recall`)、`vector_memory.py`、`entity_graph.py`
- 验收：对抗基线（kw vs 向量 vs RRF）；召回率↑、注入污染率↓。

**P1-4　LLM 成本/缓存命中率追踪 + Token 预算熔断**
- 依据：3.5（成本在缓存读取）、8.5（成本核心瓶颈）
- 模块：`llm_vllm_provider.py`、`llm_hybrid_provider.py`、`config.py`、`target_orchestrator.py`
- 验收：每次调用记录 input/output/cache-hit/费用估算；超预算熔断并留痕。

**P1-5　上下文压缩策略落地验证（6 轮以上 + 压缩）**
- 依据：2.3（防上下文爆炸）、4.3（6 轮压缩）
- 模块：`target_orchestrator.py`、`context_manager.py`、`target_memory.py`
- 验收：长对话不溢出；摘要保留关键结论/事实；压缩有日志。

### P2（演进与观察，按需投入）

| 编号 | 建议 | 依据 | 模块 |
|---|---|---|---|
| P2-1 | 管理闭环后台任务（M4）：幂等/游标/事件日志/审计/预算 | 1.2 / 1.4 | `target_memory.py`、`reflection.py` |
| P2-2 | 实体图多跳 + evidence 回链；可选梦境引擎（M5） | 1.1 / 6.4 | `entity_graph.py`、`associations.py`、`communities.py` |
| P2-3 | 多 Agent 松耦合/子代理交接试点（先"固定对话绑定单一 Agent"） | 2.2 / 2.3 | `target_orchestrator.py`、`target_entry.py` |
| P2-4 | Surface/Tunnel 分层纠错评估（Tunnel 纠正 Surface 输出） | 2.6 | `target_chain.py`、`llm_reasoner.py` |
| P2-5 | 本地推理 llama.cpp + 量化评估（成本/兼容性） | 3.1 / 3.2 / 3.8 | `llm_vllm_provider.py`、`yhlz_paths.py` |
| P2-6 | 稀疏化 / 世界模型 / JEPA 观察跟踪（**不落地**） | 5.x / 6.3 / 6.4 / 6.5 | —（研究跟踪） |

---

## 4. 结论

1. **知识面**：8 主题中，YHLZ 在"记忆人格""工具安全""开发方法"三条上已有较扎实的落地；"Agent 架构"有注册表+调度器骨架但**未接入目标语音链**；"语音多模态"边界齐全但**全双工 C 未真机验证**；"推理部署/学习世界模型"为弱项；"稀疏化"在项目范围外。
2. **最大结构性问题**：**两条 turn 路径割裂**——安全门与能力注册表只在 daemon 路径，目标语音链未受同等约束。这既是主题 2 的缺口，也是主题 7 的风险点，故列为 P0-1。
3. **最该先做的三件事**：P0-1（路径统一）、P0-2（写防火墙全覆盖）、P0-3（真机证据验收）。
4. **诚实边界**：本报告未做任何实现改动；所有"未验证"能力均以现状标注，未以链路状态或日志代替正面结论。

---

## 附录 A　证据索引（文件:行）

- 能力注册表 fail-closed：`backend/target_capability_registry.py:173-209`、`:125-128`
- 控制面政策永不导出：`backend/target_capability_registry.py:38,152-155`
- 编排器接入注册表：`backend/target_orchestrator.py:249-250,332-337,365`
- 语音链未接注册表：`backend/target_composition.py`（无 registry import）、`backend/target_chain.py:902`
- 宪法确定性预检：`backend/target_constitution.py:31`
- 记忆只读门面：`backend/memory_guard.py`
- 全双工/取消：`backend/session_kernel.py:52,559`、`backend/target_chain.py:598`、`backend/target_playback.py:211`、`backend/target_runtime.py:163,466`
- 记忆分层/检索：`backend/target_memory.py:12,269,284-285,327,382,400-407`
- 图/联想：`backend/associations.py:29`、`backend/communities.py:83`、`backend/entity_graph.py:78`
- 成本/上下文预算：`backend/target_orchestrator.py:25,387-390`、`backend/config.py:331`

## 附录 B　来源文件

- `docs/知识汇编/QQ-主题总结-2026-09-06.md`
- `docs/报告/QQ技术周报_2026-09-10.md`
- `docs/技能库/QQ知识捕获工作流.md`、`docs/技能库/数据口径与格式.md`
- `docs/ADR-001`~`ADR-007`
- `docs/YHLZ2.0_VoiceIdentitySystem_架构设计白皮书.md`、`docs/Session-Kernel-Protocol-v1_草案.md`
- `docs/YHLZ_记忆架构_设计_v2.md`
- `下载物象/QQ技术知识总汇-8主题-2026-09-14.md`（本报告知识底座）

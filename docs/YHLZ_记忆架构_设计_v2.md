# YHLZ 记忆架构设计 v2

> 2026-09-12 · 设计稿（**不改实现**，先设计→台账→再分阶段落地）
> 参考：工业"四层冷热"综述（`下载物象/记忆改造技术资料.txt`）、CX-O 记忆/进化/梦境研究
> （`docs/参考研究/CX-O-记忆进化梦境研究.md`）、NEKO 记忆系统（`N.E.K.O/docs/architecture/memory-system.md`、
> `memory-event-log-rfc.md`、`memory-evidence-rfc.md`）、以及 YHLZ 现有实现与本轮 A/B/C/D 修复。

---

## 0. 目标与硬约束

- 定位：**数字生命**（非扮演）——记忆要能"生长、内化、被主动想起"，而非仅存储检索。
- 硬件：RTX 4060 8GB；LLM(Gemma) / ASR / TTS 不可同驻；记忆侧一律 **CPU/本地**（bge-small + bge-reranker）。
- 铁律：**零删除**（只降权/归档/软删）；**人在环**（身份/认知变更须批）；**透明可审计**（明文文件+快照回滚）；**不训参数**（放弃端到端记忆模型）。
- 中文优先、确定性、可降级（任一路失败不硬挂）。

---

## 1. 参考资料要点（摘要）

### 1.1 工业"四层冷热"（原文本）
- **L0 上下文 / L1 工作 / L2 会话 / L3 长期**；默认只载 L0+L1，按需召回，省 80~90% token。
- 三机制：**写入=LLM 抽取原子事实**（非原文）；**检索=向量+BM25+元数据+时间衰减**；**管理=Write-Manage-Read 闭环**（后台去重/合并/摘要/遗忘，如 AutoDream）。
- **L3 双层**：**画像层 Profile**（精确读，"错一次是事故"）vs **情景层 Episodic**（向量检索）。
- 五方案栈：Text2Mem（原子操作语言）→ Mem0（中间件）→ Letta（OS 自管）→ ReMe（文件即记忆）→ memU（记忆即 Agent）。
- 四短板：①被动记忆 ②检索准确率 ③冲突靠规则 ④记忆不"生长"。

### 1.2 CX-O（借鉴）
- 记忆：SQLite 分型 + `permanent` 豁免（importance=1.0 零衰减、主模型可写副模型不可删）；向量(Weaviate) hybrid（向量0.6+LIKE0.4）；实体图（md5(name:type) 节点 + evidence_memory_ids 回链，默认懒加载）；双阶段指数衰减（permanent 豁免、召回再激活）；蒸馏 9 状态机 + quality 拒收 + **human override 审批**；5 级归档软删+审计。
- **梦境引擎**：入睡自动日小结 → 采近 7 天边缘记忆+图谱孤立节点 → LLM 联想 3 候选 → **确定性闸门**（拦事实断言/触碰 permanent/低清醒度）→ 独立 DreamBuffer(TTL 72h) → 醒后 `surface_probability` 主动推 → `confirm=写 type='dream'（is_ground_truth=False）+ 加权非事实化` / `reject=留痕 30d`。任意文本"在吗/醒醒"可 `wake_up()` 打断。
- 进化：独立微服务、低峰窗(02-05)+样本阈值+每日幂等、旁路化、Token 预算熔断、全审计。

### 1.3 NEKO 记忆系统（标准基准）
- **每角色流水线**（非单一向量库），层各不同写路径/保留/注入行为：
  - **Working context**（`GET /new_dialog` 渲染出的上下文，非独立库）
  - **Recent memory**（`recent.json`：有界轮次 + 就地 `SystemMessage` 摘要 memo；map-reduce；硬上限）
  - **time_indexed_original**（SQLite：**时序原始账本=事实源**；**不进每次 prompt**）
  - **Facts**（原子观察，带 subject/importance/event time；hash+文本去重，可用向量找改写；被反思消费后标 `absorbed`，移入 `facts_archive.json`）
  - **Reflections**（证据打分；生命周期 pending/confirmed/promoted/merged/denied/archived；id 由来源 fact ids 派生=**幂等**）
  - **Persona**（按实体分组：master/neko/relationship；角色卡条目 `protected`，不受衰减/归档清理；证据驱动晋升经 **correction-tier merge**；矛盾进 `persona_corrections.json` 队列）
- **召回**：新对话路径**不做语义全库搜**（只 persona+reflections+recent）；按需召回=hybrid BM25+可选 ONNX 向量+**RRF**，**延迟路径不加 LLM rerank**。
- **韧性**：`outbox.ndjson` + event log + 游标 + 对账 + 衰减/归档清扫；存储启动栅栏；派生索引可重建、可失效。

---

## 2. 现有 YHLZ 记忆架构（盘点）

| 层 | 现状 | 说明 |
|---|---|---|
| L0 上下文 | `history[-6:]` 注入 | — |
| L1 工作 | `TargetMemoryService._turns` + `_summary`（滚动窗口+压缩摘要） | 本轮已**持久化** `<db>.l1.json` |
| L2 长期 | `cache/memstore/memstore.db` `l2_items`（belief/evidence/salience/source）+ `l2_fts` + `cache/embvec.db` + `cache/search/kw_index.db` | 本轮已修 FTS 去重、去重键内容化、不再复活、召回双计、L1 持久化 |
| L3 认知/人格 | `docs/元亨认知根基.md` + `memory/*.md`（golden）+ `data/persona_dims.json` + `cache/drives.json`（内在因） | 审批制；快照回滚（本轮已修 WAL 一致性+派生库） |
| 图/联想 | `entity_graph.db` + PPR `associations` + Louvain `communities` | 轻图；本轮修连接泄漏/事件循环 |
| 冲突 | `memory_judge`（关键词触发）+ `belief_step`（单标量单时钟）| **待统一（用户要求）** |
| 反思/巩固 | `reflection`（本轮加幂等 id/status/原子写）→ `target_persona_loop` consolidate → 认知根基（本轮加 absorbed 归档） | — |
| 知识库 | `data/yuanheng_kb.db`（KB，非人格记忆） | 本轮修 FTS5(trigram)+注入推理+清理 |

**与基准差距**：①L2 未显式分 Profile/Episodic ②检索仍"单路+延迟路径 rerank"，无 RRF ③冲突=规则+单标量，非证据双时钟 ④管理闭环无游标/事件日志 ⑤无梦境/联想沉淀 ⑥后台任务多处 fire-and-forget。

---

## 3. 新架构：**"四层 + 双系统 + 三闭环"**

```
L4 认知根基  元认知 / 信念 / 世界观 / 人格 / 内在因      （审批制，明文文件，慢变）
L3 画像 Profile   身份 / 用户事实 / 偏好 / 关系          （精确读 KV，protected，近不衰减）
L2 情景 Episodic  事件 / 经验 / 对话片段 / 知识           （混合检索，时间衰减，可归档）
L1 工作记忆   会话滚动窗口 + 压缩摘要                     （有界，持久化）
L0 上下文     当前轮 LLM 原生
```
**双系统**：Profile（"你是谁"，精确、保护、错一次是事故）↔ Episodic（"发生过什么"，模糊、向量、可衰减）。
**三闭环**：写入闭环（抽取→去重→冲突裁决→写入）/ 管理闭环（后台整理）/ 读取闭环（自动注入 vs 工具召回）。

### 3.1 分层与数据模型
- `l2_items` 增 `kind ∈ {profile, episodic}` 与 `protected BOOL`、`status ∈ {active, cold, absorbed, archived, rejected}`（软删，永不物理删）。
- **Profile 条目**：走精确读（按 key/实体/关系）；`protected`（人格/身份/老爹关系）不受衰减/归档清扫。
- **Episodic 条目**：走向量+BM25；有 belief/salience/时间。
- 具体存储：Episodic 用现有 memstore；Profile 建议**独立表 `profile_items`**（KV/关系型，精确读）或 `l2_items` 子集 + 索引；两者共享 `source/evidence_ref`。

### 3.2 写入闭环（Write）
`原话 → LLM 抽取原子事实（双 LLM：提取 + 校验，借 Mem0/CX-O）→ 归一(内容哈希+语义改写)去重 → 冲突检测 → 证据裁决 → 分类(profile/episodic) → 写入(带 provenance/evidence_ref/created)`
- 事实类**自主写入**（现状决定）；身份/认知类 → PENDING 待批。
- 幂等：id 由内容归一或来源派生；重复=刷新/合并，不新增。

### 3.3 冲突消解（统一，只事实域）
- **统一替代**现 `memory_judge`：单一"证据裁决器" `resolve(new, old)`。
- 依据**证据**自动裁决 `new | old | merge | uncertain | supersede`：来源可信度（老爹>自主>群>web）、时间新近、佐证次数、显著度、是否 protected。
- 不确定 → **趁机问老爹**（可插话，不阻塞）；protected/认知层冲突 → 必走审批。
- 双时钟（借 NEKO）：`reinforcement`（半衰 ~30d）+ `disputation`（半衰 ~180d），**读时合成 effective**，替代单标量 belief。
- 裁决**留痕**（`rejected`/`merged_from_ids`），可审计、可回滚。

### 3.4 读取闭环（Read）
- **自动注入（严格、少而准）**：只注入 Profile 高相关 + 少量 Episodic（**相关性门槛 + 字数上限**，本轮已加"≥2 共享 2-gram"）。
- **工具召回（宽、按需）**：hybrid **BM25 + 向量 + 元数据(时间/类型/来源) + 时间衰减**，用 **RRF 融合**；**延迟路径不做 LLM rerank**（rerank 仅离线/工具路径可选）。
- 两条路径分离，避免"相似度≠相关性"污染。

### 3.5 管理闭环（Manage，后台）
- 闲置/低峰触发（如 30min 无对话 或 每 N 轮）：去重合并、摘要、社区摘要、关联扩散、归档清扫、FTS/向量重建。
- **必须**：幂等、游标、事件日志/outbox、失败可重试、Token 预算熔断、全审计（借 NEKO event-log + CX-O 审计）。
- 替代当前 fire-and-forget。

### 3.6 成长/涌现（YHLZ 强项，继续）
- `consolidate`：碎片 → 分级主张 → 认知根基/persona（已实现，本轮加 absorbed 归档）。
- **实体图升级**：多跳 + evidence 回链（借 CX-O/KG），供联想/多跳推理。
- 技能：成功多工具链 → 技能草稿（待批）。

### 3.7 梦境引擎（可选，借鉴 CX-O）
入睡自动日小结 → 边缘记忆（近 7 天低显著+图谱孤立节点）联想候选 → **确定性闸门**（拦事实断言/触碰 protected）→ 独立缓冲 TTL → 醒后主动"讲梦" → 老爹确认=**加权非事实化**（`type=dream`, `is_ground_truth=false`）；`reject` 留痕。与现有"审批+证伪"文化天然契合。

### 3.8 保护与回滚
- `protected`/permanent 段（人格/身份/关系）不受衰减与自动清扫；只经审批。
- 快照：明文文件 + DB（本轮已改 WAL 一致性备份 + 纳入派生库）；一键回滚。

---

## 4. 迁移路线（分阶段，防花瓶；每步真机可验证）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M1** | Episodic/Profile 显式分层（`kind`/`protected`）；Profile 精确读；protected 免衰减 | 单测+真机：Profile 命中精确、protected 不衰减 |
| **M2** | 证据模型升级（双时钟 effective）+ **统一冲突裁决器**（替代 `memory_judge`，只事实）| 裁决样例集准确率；不确定→问老爹 |
| **M3** | 检索闭环：RRF 融合 + 自动注入/工具召回分离 + 门槛 | 检索对抗基线；注入污染率下降 |
| **M4** | 管理闭环后台任务（幂等/游标/事件日志/审计/预算） | 长跑 soak；幂等重放一致 |
| **M5** | 实体图升级（多跳+evidence）+（可选）梦境引擎 | 多跳召回样例；梦境 confirm/reject 留痕 |

每阶段：**先设计+台账 → 改 → 单测 → 真机 → 快照 → 提交**；不做"半接线"。

---

## 5. 验收指标（长期）

- 台账 QA ≥ 13/15（现 10/15，缺口=LLM 鲁棒性/一致性）。
- 检索：对抗基线（kw vs 向量 vs RRF）+ 召回率/污染率。
- 冲突裁决：样例准确率 + "不确定即问"覆盖率。
- 韧性：重启不丢（L1/派生库）；快照可回滚；零删除；幂等重放。
- 生长：consolidate 产出可审；梦境/联想可追溯。

---

## 6. 与现有实现差异速览

| 维度 | v1（现状） | v2（本设计） |
|---|---|---|
| 分层 | L0-L2 混一表 | **Profile / Episodic 显式分离** |
| 证据 | 单标量单时钟 | **双时钟 effective + 裁决留痕** |
| 冲突 | `memory_judge` 规则 | **统一证据裁决器（自动+可问）** |
| 检索 | 单路 + 延迟 rerank | **RRF 混合 + 双路径分离 + 门槛** |
| 管理 | fire-and-forget | **幂等闭环 + 游标/事件日志/审计** |
| 生长 | 巩固→认知 | **+实体图多跳 / 梦境沉淀** |
| 保护 | 认知根基审批 | **+protected 段免衰减 + rejected 留痕** |

---

## 7. 研究佐证与优化（2026-09-12 补充；查证 GitHub/arXiv）

> 目的：用开源实现与论文**佐证/修正**本设计。以下均为公开资料（GitHub + arXiv）。

### 7.1 佐证（与本设计一致）
| 来源 | 关键点 | 佐证本设计 |
|---|---|---|
| **Mem0**（`mem0ai/mem0`，65k⭐；arXiv:2504.19413） | 新算法改为 **单次 ADD-only 抽取**（不 UPDATE/DELETE，记忆只增不覆写）、**agent 产生的事实一等公民**、**实体链接**、**multi-signal 检索**（语义+BM25+实体并行融合）、**temporal reasoning**；LoCoMo 92.5 / LongMemEval 94.4 | ③④"证据驱动/不改写"、多信号融合、实体增强 |
| **Graphiti / Zep**（`getzep/graphiti`，31k⭐；arXiv:2501.13956） | **双时态知识图**：每条事实带**有效期窗口（valid_at/invalid_at）**，变更时**失效而非删除**；**episodes=provenance**（可溯源原始数据）；hybrid（语义+BM25+**图遍历**） | ③"supersede/失效不删"、provenance、混合检索 |
| **A-MEM**（arXiv:2502.12110，NeurIPS'25） | Zettelkasten 式**互链笔记**+动态索引；**memory evolution**（新记忆触发旧记忆上下文/属性更新）；agent 驱动 | ⑥"记忆生长/联想"、实体互链 |
| **HippoRAG 2**（arXiv:2502.14802 / 2405.14831，ICML'25/NeurIPS'24） | KG + **Personalized PageRank** 做**联想/多跳**检索；比 GraphRAG/RAPTOR/LightRAG **更省资源** | 已有 `associations.py`(PPR)+`communities` 方向**正确**；资源友好 |
| **LongMemEval**（arXiv:2410.10813，ICLR'25） | 长时记忆 **5 能力**：信息抽取 / 多会话推理 / 时间推理 / **知识更新** / **弃答(abstention)**；3 阶段 indexing/retrieval/reading；优化=**会话粒度切分**、**事实增强的 key 扩展**、**时间感知 query 扩展** | 验收维度 + 检索优化点；**"弃答"应正式纳入**（对齐"不确定就问"） |
| **Letta/MemGPT**（`letta-ai/letta`，25k⭐） | OS 虚拟内存思想，stateful agent 自管记忆、self-improve（core/working/archival/recall + sleeptime） | ②"自主管理/后台整理"、"记忆即 Agent"方向 |

### 7.2 据研究修订/优化 v2

1. **冲突 = "失效不删 + 双时态窗口"（采纳 Graphiti）**：不做"覆盖旧记忆"，而是给旧条目 `invalid_at`/`superseded_by`，新条目 `valid_at`；查"当前事实"取未失效者，历史完整保留。**比规则覆盖更安全，且天然满足"零删除"**。
2. **保守模式 = ADD-only（采纳 Mem0）**：若证据裁决不稳，可退化为"**只增不改 + 时间推理**"，把"谁对"交给**读取时**按时间/证据/来源排序。**给 M2 一个可降级档**（默认"裁决+失效"，兜底"ADD-only"）。
3. **检索升级 = multi-signal fusion + 实体匹配（Mem0/Graphiti）**：语义 + BM25 + **实体匹配** 并行、融合（RRF）；由 `entity_graph` 供实体信号（即"实体增强的 key 扩展"）。
4. **联想升级 = 多类型节点 + PPR（HippoRAG2）**：实体图从"实体-关系"扩为 **passage + entity + phrase** 多类型；用 PPR 做联想召回并与向量/BM25 融合（我们已有 PPR，属"验证正确方向 + 扩展"）。
5. **验收纳入 5 能力（LongMemEval）**：抽取 / 多会话推理 / 时间推理 / 知识更新 / **弃答**；其中"弃答"正式成为她的显式能力（不确定→不编→可问）。
6. **检索三优化（LongMemEval）**：①**会话粒度切分**（抽取按会话/事件粒度，而非单句）②**事实增强的 key 扩展**（索引时把事实/别名并入 key）③**时间感知 query 扩展**（涉"现在/当时/计划"时按时间窗扩展）。
7. **memory evolution（A-MEM）谨慎采纳**：新记忆可更新旧记忆的**派生字段**（关联、摘要、上下文），但**不改事实本身**，且留 version/证据——防"污染事实"。

### 7.3 结论
- v2 的**分层（Profile/Episodic）、证据/失效、混合检索、图联想、人在环**均被 2025–2026 主流工作**佐证**；**无需推翻**。
- **据研究微调 3 处**：③冲突改"**双时态失效**"（+ADD-only 兜底）、④检索加"**多信号+实体**"融合、⑤验收加"**弃答**"与检索三优化。
- 明确**不采纳**：需要外部图数据库/高显存（Zep/Neo4j、HippoRAG 全量 vLLM）、端到端记忆模型（继续不训参数）。

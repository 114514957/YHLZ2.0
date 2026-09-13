# YHLZ · M2（统一证据裁决器）+ 微调数据管道 设计

> 2026-09-12 · 两条并行线。**先设计→台账→再落地**；每步真机可验证。

---

## A. M2：统一证据裁决器（事实域）

### A0. 目标 / 非目标
- 目标：把现有"**关键词触发**的 `memory_judge`"升级为**统一、证据驱动**的冲突裁决；**高置信才自动失效**（软失效、可回滚），否则并存 / 趁机问。
- 只做**事实域**（L2 episodic/fact）；画像/身份冲突仍走审批。**不删**。

### A1. 触发与候选
- 触发：新条目写入后，扫描**同主体**（entity_graph 实体 / 关键词交集）的现有 active 条目。
- 候选对：`(new, old)`，要求**实体重叠**且（谓词相近 或 明显同域）。

### A2. 证据信号（每条可解释、可审计）
| 信号 | 说明 | 权重 |
|---|---|---|
| `source_trust` | 老爹 1.0 / agent 0.6 / 群 0.3 / web 0.2 | 高 |
| `recency` | 新条目时间更新 | 中 |
| `corroboration` | `evidence_count`（被佐证次数） | 中 |
| `write_confidence` | 写入时 `confidence` | 中 |
| `protected` | 1 → **永不自动失效** | 否决 |
| `belief` | 现有效力 | 低 |

### A3. 决策（保守默认，四档）
1. **supersede（自动失效）**：同主体 + 同谓词 + **明确否定**（新/旧含"不/没/别/改/更正"）+ 新来源可信（老爹或高置信）→ 旧条 `invalid_at`、`superseded_by=新id`。
2. **supersede_candidate（仅记关系）**：方向明确但证据不足 → 记 `supersedes` 关系、**不失效**；读取时按 时间+证据 排序。
3. **merge**：同义改写（高相似）→ 合并（保留一条 + 佐证）。
4. **uncertain**：拿不准 → 并存 + **趁机问老爹**（可插话，不阻塞）。

### A4. 落地与接线
- 新增 `backend/memory_adjudicate.py`：`resolve(new_item, old_item) -> {action, reason, evidence}`（**纯函数 + 可单测**）。
- 接线：`target_entry` 的冲突路径（现 `_maybe_contradiction`）与 `store_item` 后置扫描调用。
- **统一替代 `memory_judge`**：LLM 裁决降为**其中一路信号**（可关），主判据=证据规则。
- 审计：每次裁决写 `growth_log`/事件（可回溯）。

### A5. 验收
- 样例集（中文 ~20）：明确否定→失效；来源弱→只记关系；protected→永不失效；同义→合并；不确定→问。
- 指标：**误失效=0**（保守默认）；可回滚；真机"改口"能高置信失效。

---

## B. 微调数据管道

### B0. 现实评估（诚实）
- **元亨人格对话**（`cache/sessions/console.json` + `qq_qq_p2258374446.json`）：**量很小（约十来轮）**——是**黄金种子**，但**远不够微调**。
- **QQ 群导出**（`.qq-chat-exporter/exports/group_*.json`，~80MB、**含重复**）：是**他人技术讨论**，**不是元亨对话** → **只能当"知识/继续预训练语料"**，**不能直接当人格 SFT**。
- 结论：**现在不足以真训练**；本阶段先**建管道、抽干净数据、持续积累**（真微调是下个里程碑，届时数据量再说）。

### B1. 两类产物
| 产物 | 来源 | 用途 |
|---|---|---|
| `data/finetune/sft_persona.jsonl` | 元亨↔老爹对话（sessions） | 人格 SFT（chatml: system/user/assistant） |
| `data/finetune/corpus_qq.jsonl` | QQ 群导出 | 知识/领域语料（继续预训练或 RAG/知识抽取） |
| `data/finetune/stats.json` | 全部 | 体量/去重/来源统计 |

### B2. 管道
1. **抽取**：sessions → `history` 配对（user→assistant）；QQ → 复用 `qqexport_ingest.iter_messages`（group_id/user_id/nickname/text/ts）。
2. **清洗**：去媒体占位/回复框/@；len 过滤；丢空。
3. **去重**：消息指纹（`group|user|text_norm`）+ 会话内相同 QA 去重；**重复导出自动合并**。
4. **格式**：SFT=chatml（system=元亨人格，沿用 `target_prompts` 的自我定位）；语料=纯文本 + 元数据。
5. **切分**：train/val（按时间/随机），落 `data/finetune/`。
6. **统计**：条数/去重/来源/长度分布 → `stats.json`。

### B3. 纪律（防花瓶）
- **不把群聊伪装成元亨对话**；不**用模型自产数据**当训练集（自产自销=退化），除非有**校验**。
- 数据可追溯（source 字段）；**不外传**（含他人隐私），仅本地。
- 体量不够就**如实说**，先积累。

---

## C. 执行顺序
1. **M2 设计落到 `memory_adjudicate.py` + 样例集 + 接线**（先设计→单测→真机）。
2. **微调数据管道 `tools/finetune_build.py`**：抽 sessions + QQ 导出 → `data/finetune/` + 统计（先跑现有素材，见真实体量）。
3. 逐步积累人格对话；真微调在数据够了再开。

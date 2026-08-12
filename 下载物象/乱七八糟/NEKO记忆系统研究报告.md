# NEKO 记忆系统源码研究报告

> 研究范围：`NEKO_src/memory/` 全部记忆模块 + `misc/config____init__.py`（config 门面）
> 说明：本文所有类名、函数、行号均以源码为准；config 门面仅 re-export 常量，真实数值位于未下载的 `config/domain` 模块中，凡标注"值在 config 领域模块，未下载"者即无法从本地确认。

---

## 目录

1. [五维记忆总览](#1-五维记忆总览)
2. [各类型记忆的写入路径与去重](#2-各类型记忆的写入路径与去重)
3. [recall / hybrid_recall 混合召回](#3-recall--hybrid_recall-混合召回)
4. [anti_repeat 防重复](#4-anti_repeat-防重复)
5. [archive_shards / temporal / timeindex 归档](#5-archive_shards--temporal--timeindex-归档)
6. [refine 精炼](#6-refine-精炼)
7. [facts 事实核心](#7-facts-事实核心)
8. [persona / reflection](#8-persona--reflection)
9. [LLM 调用硬规则](#9-llm-调用硬规则)
10. [上下文预算常量](#10-上下文预算常量)
11. [最佳实践与坑](#11-最佳实践与坑)

---

## 1. 五维记忆总览

记忆系统是 NEKO 角色（"lanlan"）的人格与历史承载层，采用**三层 tier 结构**（Tier 1 = facts / Tier 2 = reflections / Tier 3 = persona），辅以近期对话（recent）、时间索引、事件日志、防重复、精炼等横向设施。全部按角色分目录存储：`memory_dir/{name}/{type}.json`（`memory/__init__.py` 的 `ensure_character_dir` + `migrate_to_character_dirs` 负责从旧的 `{type}_{name}.ext` 一次性迁移）。

| 维度 | 存储文件 | 承载类 | Tier | 角色 |
|---|---|---|---|---|
| 事实记忆 | `memory/{name}/facts.json`（+ `facts_archive.json`） | `FactStore`（facts.py:303） | Tier 1 | 原子观察，SHA-256 + FTS5 去重 |
| 反思记忆 | `memory/{name}/reflections.json` | `ReflectionEngine` | Tier 2 | 综合/确认/晋升后的长期认知 |
| 人格记忆 | `memory/{name}/persona.json` | `PersonaManager` | Tier 3 | 稳定人格画像，动态实体条目 |
| 近期记忆 | `memory/{name}/recent.json` | `CompressedRecentHistoryManager`（recent.py:327） | 横切 | 未压缩对话 + 摘要 memo |
| 时间索引 | `memory/{name}/time_indexed.db` | `TimeIndexedMemory`（timeindex.py） | 横切 | SQLite FTS5 全文索引 |
| 事件日志 | `memory/{name}/events.ndjson` + `events_applied.json` | `EventLog` + `Reconciler`（event_log.py:194/739） | 横切 | 追加式审计 + 启动重放 |

另有 `ImportantSettingsManager`（settings.json）处理用户重要设定。

**scoped（群/成员）记忆**：自 `memory.scopes.MemorySubject` 引入后，facts/reflections/persona 均支持按 subject 分区（`subject_kind`/`subject_id`/`scope` 字段）。scoped 走"简化管线"——写盘即 `signal_processed=True`、不参与 Stage-2 evidence、时间驱动晋升——避免与 legacy 私聊主链路互相饿死（见 facts.py:3759 附近注释）。

---

## 2. 各类型记忆的写入路径与去重

### 2.1 facts（事实）

- **入口**：`aextract_facts_and_detect_signals`（facts.py:4207，两阶段）与 `extract_facts`（facts.py:4348，仅 Stage-1 兼容入口）、`_allm_extract_facts_batch`（分段批抽取，群场景）。
- **Stage-1**：纯事实抽取，prompt 不携带既有观察，避免自循环（LLM 把已有 reflection 当新 fact 抄回）。经 `_allm_call_with_retries` 调 LLM（`call_type="memory_fact_extraction"`，tier 取 `EVIDENCE_EXTRACT_FACTS_MODEL_TIER`）。
- **持久化**：`_apersist_new_facts_locked`（facts.py:3379）统一去重 + 落盘，详见第 7 节。
- **两阶段 drain**：Stage-1 写入的 fact 带 `signal_processed=False`；Stage-2 拉取**全部** `signal_processed=False` 的 legacy fact（含历史尾部），按 `importance DESC, created_at ASC` 排序取前 `EVIDENCE_DETECT_SIGNALS_MAX_NEW_FACTS` 条 → `_aload_signal_targets`（facts.py:3870）组装观察池 → `_allm_detect_signals` 产出 reinforce/negate 信号。dispatch 成功后调用方 `amark_signal_processed`。任何一环失败都保持 `False`，下轮 idle 重试（CodeRabbit c755101c 语义）。

### 2.2 recent（近期记忆）

- **写入**：`update_history`（recent.py:725）。先"读盘 + 合并未落盘批次 + append + 落盘"一个临界区（CS-1，`_append_and_persist_locked`），再在**锁外**跑 `compress_history`（LLM 数秒~数十秒，不能占锁挡 /cache）。
- **压缩**：`compress_history`（recent.py:1093）。输入超过 `RECENT_COMPRESS_INPUT_BUDGET_TOKENS` 先 `_segmented_compress` 分段 map-reduce；Stage-1 摘要 > `MAX_SUMMARY_TOKENS` 则 `further_compress` 二次压缩，最多 3 轮重试。摘要经 `_splice_compressed_locked` 在第二个临界区（CS-2）里"读盘 + 定位 + splice + 落盘"。
- **硬上限**：`enforce_hard_cap`（recent.py:1193）按**真实注入 prompt** 的原始 content token 计算，丢弃最旧非压缩文本，保留首条 memo 与最近 `max_history_length` 条。
- **review（记忆整理）**：`review_history`（recent.py:1536）快照式（snapshot 在 spawn 时拍下），LLM 在快照上修正矛盾/冗余/重复，完成后用 K 条指纹（`REVIEW_FINGERPRINT_K=3`）在**当前** history 里定位 cutoff 并 splice。返回 `('patched', new_fingerprint)` / `('white', None)`（cutoff 失配，整批丢弃）/ `('failed', None)`。每次 LLM 调用前校验 admission generation 防角色复用空烧。

### 2.3 persona（人格）

写入经 `PersonaManager`（Tier 3）：动态实体条目按 entity 分区（如 neko/master/relationship），`protected=True` 条目（角色卡）不参与 evidence；5 小时窗口内被提及 >2 次触发 suppress；矛盾检测 → 批量修正（`PERSONA_CORRECTION_BATCH_LIMIT`）；`aensure_persona` 惰性创建；legacy 自动迁移。

### 2.4 reflection（反思）

写入经 `ReflectionEngine`（Tier 2）：pending → 用户反馈确认 → confirmed → promoted。3 天无否认自动晋升（`WEAK_MEMORY_AUTO_CONFIRM_DAYS` / `WEAK_MEMORY_AUTO_PROMOTE_DAYS`）；定期 `refine_pass` 综合（`MEMORY_REFLECTION_SYNTHESIS_INTERVAL_SECONDS`）；proactive 时段触发；`surfaced.json` 记录已浮出记忆。

---

## 3. recall / hybrid_recall 混合召回

### 3.1 MemoryRecallReranker（recall.py）

`MemoryRecallReranker.aretrieve_candidates(pool, query_texts, budget, config_manager)` 统一管线：

1. **hard_filter**：丢弃 suppress / terminal / score<0 / protected 条目。
2. **coarse rank**：向量服务就绪时按 cosine top-K（K = budget × `RECALL_COARSE_OVERSAMPLE`，默认 3 倍）；未就绪时退化为按 `evidence_score` 排序。
3. **fine rank（LLM rerank）**：向量不可用时自动跳过；否则 LLM 对 top-K 精排，预算受 `RECALL_PER_CANDIDATE_MAX_TOKENS` / `RECALL_CANDIDATES_TOTAL_MAX_TOKENS` 约束。

Stage-2 的 `_aload_signal_targets` 在有 new_facts 时也走该 reranker，保证向量 warmup 期间 suppress 过滤行为一致（CodeRabbit PR-956 Major 修复）。

### 3.2 hybrid_recall（hybrid_recall.py）

`hybrid_recall`（hybrid_recall.py:564）双路并行：

- **BM25 路**：池 = facts + reflections + **facts_archive**（含归档！`_aload_archive_facts`），阈值 `HYBRID_RECALL_BM25_THRESHOLD`，budget `HYBRID_RECALL_BUDGET_EACH`。
- **余弦路**：池 = facts + reflections（**排除 archive 与 persona**），阈值 `HYBRID_RECALL_COSINE_THRESHOLD`。
- **融合**：`_rrf_fuse`（RRF，k=`HYBRID_RECALL_RRF_K`）合并两路，总量 ≤ `HYBRID_RECALL_BUDGET_TOTAL`。
- `_drop_archive_overlap`：归档行只允许在活跃集无匹配时补位，避免与活跃事实重复占据预算。
- 另有 `recall_by_time`（hybrid_recall.py:762）按时间窗召回（配合 temporal 时间场）。

`_tokenize` 支持 `stop_names`（角色名过滤）；每个条目打 tier 标签（`_tag_tier`）供渲染区分。

---

## 4. anti_repeat 防重复

`AntiRepeatCorpus`（anti_repeat.py:280）用 **BM25** 在滚动语料上做防重复与"最近话题注入"。

- **写入**：`record_output` / `stage_output`（两段式：先内存 staged，`aflush_staged` 再落盘，避免阻塞）→ 磁盘窗口快照，带 seq 单调校验，防并发丢失。
- **评分**：`score_draft`（anti_repeat.py:657）把草稿 vs 最近 `fg_window` 条 AI 输出做 BM25。窗口分 FG/BG：**FG 只统计 `ANTI_REPEAT_FG_TTL_SECONDS` 内**的条目（整窗老化后分数归 0、草稿放行——防"防重复死锁"）；BG 只贡献 DF（长未见的词拿高 IDF）。草稿过短（< `ANTI_REPEAT_MIN_DRAFT_TOKENS`）直接 `(0.0, {})`。
- **未应答 proactive 检测**：`score_unanswered_proactive_draft`（anti_repeat.py:691）在用户沉默期间检测反复出现的话题模板（与短期 BM25 互补；只在 `silence_since` 之后的 proactive 输出参与计票，任一真实用户消息即重置证据）。返回 `UnansweredProactiveRepeatSignal`，含 `match_count` / `repeated_terms`（按词频取前 `ANTI_REPEAT_INJECT_TOP_K`）。
- **话题注入**：`top_recent_topics`（anti_repeat.py:773）把最近 FG 窗口的高分 n-gram 注入下轮 system prompt，告知模型"最近聊过 X/Y/Z"。
- **配置**：`ANTI_REPEAT_BG_WINDOW` / `ANTI_REPEAT_FG_WINDOW` / `ANTI_REPEAT_FG_TTL_SECONDS` / `ANTI_REPEAT_REGEN_THRESHOLD` / `ANTI_REPEAT_DROP_THRESHOLD` / `ANTI_REPEAT_BM25_K1` / `ANTI_REPEAT_BM25_B` 等，数值在 config 领域模块（未下载）；窗口约 100 条量级（注释口径）。

---

## 5. archive_shards / temporal / timeindex 归档

### 5.1 archive_shards（分片归档）

- **文件名**：`<YYYY-MM-DD>_<uuid8>.json`（`shard_filename_for`），按天分片，`_pick_shard_path_for_today` 选择当天分片。
- **写入**：`aappend_to_shard` / `append_to_shard_sync` 追加；`ensure_entry_in_named_shard_sync` 幂等去重。单文件条目上限 `ARCHIVE_FILE_MAX_ENTRIES`（值在 config）。
- **迁移**：`migrate_flat_archive_to_shards_sync` / `amigrate_flat_archive_to_shards` 把旧的扁平归档迁为分片。
- **容错**：`ShardCorruptError`，读取损坏分片抛错而非静默吞。

### 5.2 temporal（时间场，schema v2）

- `normalize_event_when`：LLM 输出相对时间 `{offset, unit}`，系统按 `created_at` 当锚点解算成 ISO。
- `compute_event_timestamps(..., fallback_start=True, fallback_end=False)`：保证一定有 `event_start_at`，`event_end_at` 可选。
- **时间衰减**（供过期 block 渲染）：0 天 → "当下"；1–6 天 → "n 天前"；7–29 天 → "n 周前"。
- `temporal_scope` 枚举：`pattern` / `state` / `episode` / `past`。

### 5.3 timeindex（TimeIndexedMemory）

- SQLite FTS5 全文索引，表 `TIME_ORIGINAL_TABLE_NAME` / `TIME_COMPRESSED_TABLE_NAME`（值在 config），`unicode61` tokenizer（中文按字符粒度，注释口径——这也解释了 FTS5 语义去重按字符级近邻）。
- 角色级索引文件 `memory/{name}/time_indexed.db`。
- 主要方法：`aindex_fact` / `asearch_facts` / `adelete_fact_from_index`。

---

## 6. refine 精炼

`MemoryRefineEngine`（refine.py:148）：

- **流程**：`refine_pass`（refine.py:168）→ `_compute_clusters`（余弦聚类，阈 `MEMORY_REFINE_COSINE_THRESHOLD`）→ LLM 四动作（合并/拆分/重写/忽略）→ `_cluster_hash` + `_all_stamped_fresh` 保证每簇只精炼一次。
- **上限**：`MEMORY_REFINE_CLUSTER_SIZE_MAX` / `MEMORY_REFINE_CLUSTERS_PER_PASS` / `MEMORY_REFINE_REVISIT_AFTER_DAYS`（复查间隔）约束单轮成本。
- **优雅降级**：嵌入服务不可用或候选不足 → 整轮 no-op（不空烧 LLM）。
- scoped 版本走 `SCOPED_REFINE_*` 常量组（`SCOPED_REFINE_MIN_ENTRIES` 等），独立节奏。

---

## 7. facts 事实核心

`FactStore`（facts.py:303，5094 行，`memory__facts.py`）：

### 7.1 字段 schema

`_apersist_new_facts_locked`（facts.py:3379）产出的 fact_entry 字段（facts.py:3728-3777）：

```
id, text, importance(1..10 clamp), entity, source, tags(默认空),
hash(SHA-256 hex[:16]), created_at, event_when_raw, event_start_at,
event_end_at, schema_version(MEMORY_SCHEMA_VERSION_CURRENT),
absorbed(False), signal_processed(见下), embedding/embedding_text_sha256/
embedding_model_id(预热 worker 后填)
```

- **`signal_processed`**：`source=='ai_disclosure'` 或 scoped → 直接 `True`（不进 Stage-2）；否则 `False` 入队等 drain。老 fact 缺该字段读侧默认 `True`，升级不重放历史。
- **source 白名单**：`_SOURCE_VALUES`；LLM 显式 source 优先，否则 `default_source`（path A=`user_observation`，path B=`ai_disclosure`）。
- **provenance**：`speaker_provenance`（speaker_label / speaker_trust / speaker_id）只盖在**新建 user_observation** fact 上，来自调用方、绝不读 LLM 输出（防伪造）；`_reconcile_existing_provenance` 对既存行做幂等 reconcile（mixed 标记）。

### 7.2 去重（facts.py:3553-3713）

1. **Stage 1 — SHA-256 精确去重**：`hash = sha256(f"{subject_key}\n{scope}\n{text}")[:16]`；daily 导入用 `"{event_date}\n{text}"` 做盐（同一天重试幂等，**跨日期重复事件各自落盘**）。
2. **Monotonic source 升级**：SHA 命中且 `existing.source=='ai_disclosure'` + 新 `source=='user_observation'` → in-place 升级 + `signal_processed=False` 重入 Stage-2；反向永不降级。
3. **Stage 2 — FTS5 语义去重**：`asearch_facts` 取 top-10 候选 → 只统计**同 subject** 候选（`entry_matches_subject`），首窗同 subject ≥3 或命中不足则扩窗到 200 重扫（扇出场景）→ score ≤ -5 判定重复（`daily_event_date` 跨日期豁免）。`subject_archived_at` / `arbitration_archived_at` 归档行不挡去重（subject 复活重述必须能落新）。`semantic_dedup=False`（外迁批）只做精确去重，省锁内 FTS5 开销。
4. **归档行查重**：FTS 命中不在活跃集时惰性读 `facts_archive.json` 判重，防"归档后同文本绕过查重"。

### 7.3 落盘与回滚（facts.py:3815-3868）

- 新 fact 或升级或 provenance 变更才 `asave_facts`。
- **回滚纪律**：FTS 索引失败或落盘失败 → `_rollback_uncommitted_facts`（facts.py:5029）还原 in-place 升级 + 从缓存剔除新增 + 从 hash 集 discard + 删 FTS 行。否则 fail-closed 重试会撞去重拿"空成功"、调用方推游标而磁盘永无此数据。
- 缓存只在落盘成功后动（对齐 event_log 纪律）。

### 7.4 归档（facts.py:1905）

- `_archive_absorbed`：把 `absorbed=True` 且 `created_at` 早于 `_ARCHIVE_AGE_DAYS`（=7 天）的 fact 移入 `facts_archive.json`。
- **提交顺序固定"先 archive 再 facts.json"**：中断窗口状态是"两边都有"（读侧 `load_facts_full` 按 id 收敛、下轮按 id 幂等追加），而不是"两边都没有"（永久丢已归档 fact + daily import 指纹 → 整天重导）。
- `_merge_archive_entries` 按 id 幂等合并（半提交自愈）。
- 另有 scoped subject 归档：`_archive_subject_facts`（facts.py:1971，时间驱动，`SCOPED_SUBJECT_ARCHIVE_ENABLED` / `SCOPED_SUBJECT_STALE_DAYS`）。

### 7.5 读取侧

- `load_facts_full`：活跃 + 归档按 id 收敛合并读。
- `get_unabsorbed_facts`（facts.py:5013）默认 `min_importance=5` 过滤（importance<5 的 fact 照存，读取时才过滤）；`aget_unabsorbed_facts` 加 `safe_importance` 防手改非数值行 TypeError。
- `mark_absorbed` / `amark_absorbed`（reflection 消费后打标）。
- `_aload_signal_targets`（facts.py:3870）：reflections(confirmed/promoted) + persona(非 protected) → subject 边界过滤 → reranker 精排。

---

## 8. persona / reflection

### 8.1 PersonaManager（Tier 3）

- **实体分区**：persona.json 按 entity_key 分 section，每个 section 下有 facts 列表；`protected=True`（角色卡）不参与 evidence。
- **suppress 机制**：5 小时窗口内被提及 >2 次 → 标记 suppress，召回/渲染/evidence 全过滤（`_aload_signal_targets` 中 `entry.get('suppress')` 一并传给 reranker 的 hard_filter）。
- **矛盾处理**：检测到矛盾 → 批量修正（`PERSONA_CORRECTION_BATCH_LIMIT`），`persona_corrections.json` 存修正记录。
- **渲染**：`PERSONA_RENDER_MAX_TOKENS` / `PERSONA_RENDER_ENCODING` 预算；`aensure_persona` 惰性初始化；legacy 迁移自动。

### 8.2 ReflectionEngine（Tier 2）

- **状态机**：pending →（用户反馈确认）→ confirmed →（晋升）→ promoted；`surfaced.json` 记录浮出。
- **自动晋升**：`WEAK_MEMORY_AUTO_CONFIRM_DAYS` / `WEAK_MEMORY_AUTO_PROMOTE_DAYS`（默认 3 天量级，无否认自动确认/晋升）。
- **evidence score**：`memory.evidence.evidence_score(entry, now)` 综合确认/否决增量与时间半衰期（`EVIDENCE_REIN_HALF_LIFE_DAYS` / `EVIDENCE_DISP_HALF_LIFE_DAYS`）。
- **综合**：`refine_pass` 定期把未吸收 facts 合成为 reflection；`REFLECTION_SYNTHESIS_FACTS_MAX` / `REFLECTION_SYNTHESIS_CONTEXT_ABSORBED_COUNT/DAYS` 控制输入；综合耗时任务有 `MEMORY_REFLECTION_SYNTHESIS_INTERVAL_SECONDS` 节流。
- **召回**：`REFLECTION_SURFACE_TOP_K` / `REFLECTION_RELATED_PER_QUERY_K` / `REFLECTION_RELATED_TOTAL_CAP`。
- **proactive 触发**：仅 proactive 会话期间触发综合/晋升。

---

## 9. LLM 调用硬规则

记录于 `memory/__init__.py`（memory____init__.py:17-48），全项目级：

1. **不传 `temperature`**：经 `utils.llm_client.create_chat_llm` / `ChatOpenAI` 的一切调用禁止 `temperature=`。兼容拒绝该参数的模型（o1/o3/gpt-5-thinking/Claude extended-thinking），且固定温度易引发难复现回归。gatekeeper = `scripts/check_no_temperature.py`（CI：`.github/workflows/analyze.yml`）。`FactStore._allm_call_with_retries` 历史上接受 `temperature=`，已删除。
2. **模型全部走 tier，禁止硬编码回退**：经 `self._config_manager.get_model_api_config('summary'|'correction'|...)` 取 `model/base_url/api_key` 三元组。tier 未配置时 `api_config['model']` 为 `''`，请求被 API 显式拒绝（配置错误直接浮出，不用 qwen-max 兜底）。
3. **tier 使用面**：fact 抽取 / 信号检测 / reflection 综合 / fact 去重 / recall rerank → `summary`；recent.review + persona.correction + promotion merge → `correction`。
4. 豁免必须删 gatekeeper 脚本并在 PR 说明理由。

其他调用纪律（代码注释提炼）：
- `_allm_call_with_retries`（facts.py:2651）：默认 `timeout=60s`、`max_retries=3`；失败返回 `None` 由调用方决定 fail-open（容忍 `[]`）还是 fail-closed（抛 `FactExtractionFailed`）。
- 所有 LLM 调用带 `call_type`（`set_call_type` / `call_type=`）供 token 审计；`memory_review` 等路径在调用前 `set_call_type("memory_review")`。
- 大输入走分段 map-reduce（`_segmented_compress`、`_allm_extract_facts_batch`），控单次输入预算。

---

## 10. 上下文预算常量

以下常量从 `config` 门面确认存在（`config____init__.py` memory_settings/session_settings 导出），**数值大多在未下载的 domain 模块中**：

### 10.1 近期记忆（RECENT_*）
| 常量 | 本地可得值/说明 |
|---|---|
| `RECENT_HISTORY_MAX_ITEMS` | 未下载 |
| `RECENT_COMPRESS_THRESHOLD_ITEMS` | 未下载（压缩阈值，history 超阈值即压） |
| `RECENT_SUMMARY_MAX_TOKENS` | 注释确认 **1000**（+100 余量=1100 是判满信号） |
| `RECENT_PER_MESSAGE_MAX_TOKENS` | 注释确认每条 **≤500**（压缩输入截断） |
| `RECENT_COMPRESS_INPUT_BUDGET_TOKENS` | 未下载（超此值走分段压缩；CJK 700 字 ≈ 1050 token 注释） |
| `RECENT_HARD_CAP_TOKENS` | 未下载（硬上限，`enforce_hard_cap`） |
| `RECENT_SUMMARY_STALE_HOURS` | 未下载（past block 过期提醒节奏，每 N 小时） |
| `MAX_SUMMARY_TOKENS` | recent.py 内部，> 此值触发二次压缩 |

### 10.2 召回 / 渲染
`RECALL_COARSE_OVERSAMPLE`（默认 3×）、`RECALL_PER_CANDIDATE_MAX_TOKENS`、`RECALL_CANDIDATES_TOTAL_MAX_TOKENS`、`RECALL_RENDER_ENTRY_MAX_TOKENS`、`RECALL_RENDER_TOTAL_MAX_TOKENS`、`PERSONA_RENDER_MAX_TOKENS`、`REFLECTION_RENDER_MAX_TOKENS`、`SCOPED_RENDER_TOTAL_MAX_TOKENS`。

### 10.3 混合召回 / 证据
`HYBRID_RECALL_BUDGET_EACH`、`HYBRID_RECALL_BUDGET_TOTAL`、`HYBRID_RECALL_TIME_BUDGET`、`HYBRID_RECALL_COSINE_THRESHOLD`、`HYBRID_RECALL_BM25_THRESHOLD`、`HYBRID_RECALL_RRF_K`、`EVIDENCE_DETECT_SIGNALS_MAX_NEW_FACTS`、`EVIDENCE_DETECT_SIGNALS_MAX_OBSERVATIONS`、`EVIDENCE_PER_OBSERVATION_MAX_TOKENS`、`EVIDENCE_OBSERVATIONS_TOTAL_MAX_TOKENS`、`EVIDENCE_CONFIRMED_THRESHOLD`、`EVIDENCE_PROMOTED_THRESHOLD`、`EVIDENCE_ARCHIVE_THRESHOLD`、`EVIDENCE_ARCHIVE_DAYS`、`WEAK_MEMORY_AUTO_CONFIRM_DAYS`、`WEAK_MEMORY_AUTO_PROMOTE_DAYS`、`EVIDENCE_REIN_HALF_LIFE_DAYS`、`EVIDENCE_DISP_HALF_LIFE_DAYS`、各 `*_DELTA`。

### 10.4 防重复 / 会话
`ANTI_REPEAT_BG_WINDOW`、`ANTI_REPEAT_FG_WINDOW`、`ANTI_REPEAT_FG_TTL_SECONDS`、`ANTI_REPEAT_REGEN_THRESHOLD`、`ANTI_REPEAT_DROP_THRESHOLD`、`ANTI_REPEAT_BM25_K1`、`ANTI_REPEAT_BM25_B`、`ANTI_REPEAT_MIN_DRAFT_TOKENS`、`ANTI_REPEAT_INJECT_TOP_K`、`ANTI_REPEAT_UNANSWERED_*`、`ANTI_REPEAT_EXEMPT_SOURCE_TAGS`、`SESSION_ARCHIVE_TRIGGER_TOKENS`。

### 10.5 精炼 / 归档 / 其他
`MEMORY_REFINE_COSINE_THRESHOLD`、`MEMORY_REFINE_TOPK_PER_ENTRY`、`MEMORY_REFINE_CLUSTER_SIZE_MAX`、`MEMORY_REFINE_REVISIT_AFTER_DAYS`、`MEMORY_REFINE_CLUSTERS_PER_PASS`、`MEMORY_REFINE_CRON_INTERVAL_SECONDS`、`ARCHIVE_FILE_MAX_ENTRIES`、`MEMORY_SCHEMA_VERSION_CURRENT`、`MEMORY_LLM_HARD_TIMEOUT_SECONDS`、`LLM_OUTPUT_GUARD_MAX_TOKENS`、`SCOPED_SUBJECT_STALE_DAYS`、`SCOPED_HISTORY_BATCH_MAX_SEGMENTS`、`SCOPED_HISTORY_BATCH_MAX_MESSAGES`、`SCOPED_HISTORY_PER_MESSAGE_MAX_TOKENS`、`SCOPED_HISTORY_BATCH_CONTENT_MAX_TOKENS`、`SCOPED_BATCH_SEGMENT_NONCE_BYTES`、`VECTORS_*`（embedding 维度/量化/最小内存/warmup 延迟）、tier 常量 `EVIDENCE_EXTRACT_FACTS_MODEL_TIER` / `EVIDENCE_DETECT_SIGNALS_MODEL_TIER` / `EVIDENCE_NEGATIVE_TARGET_MODEL_TIER` / `EVIDENCE_PROMOTION_MERGE_MODEL_TIER`。

---

## 11. 最佳实践与坑

### 一致性 / 原子性
- **"先写事件、再写视图"**：event_log 先 append 到 events.ndjson，再写视图文件；`events_applied.json` sentinel 记录已应用事件 ID。启动时 `Reconciler.areconcile` 重放未应用事件（event_log.py:739）。`compact_if_needed` 按行数阈值压缩事件文件。
- **"cache only changes after the disk write"**：facts/recent/archive 均只在落盘成功后更新缓存；半提交一律回滚（`_rollback_uncommitted_facts`）。
- **提交顺序**：facts 归档固定"先 archive 再 facts.json"；recent 压缩固定 CS-1 append → 锁外 LLM → CS-2 splice，两次临界区之间崩溃不会丢新消息。
- **幂等**：归档追加按 id 合并；recent 用 `_msg_identity`/`_msg_content_sha256` 指纹防重复；facts 用 SHA-256（daily 加 event_date 盐）。

### 并发与锁
- 每角色一把 `threading.Lock`（`_get_lock`）+ 一把 `asyncio.Lock`（`_get_persist_alock`）。
- **锁不可重入**：`on_compress_done` 回调必须放在所有临界区之外（dead-letter 分支会同步调 `enforce_hard_cap` 拿同一把锁，挪进去就是 worker 线程无超时死锁）。
- review 提交的读/定位/splice/落盘必须是**一个**临界区（`_commit_review_locked` 在 worker 线程里 `_await_recent_mutation_to_completion` 串行化）。
- 快照式 mutation 用 admission generation（recent_file 的 expected_generation）校验，防止角色被复用/云导入替换后旧任务空烧或误写。

### fail-closed vs fail-open
- 对话路径事实抽取失败默认吞掉返回 `[]`（下一轮/后台循环重试）。
- scoped_history / daily 导入 / outbox 重放必须 fail-closed（`fail_closed=True` 抛 `FactExtractionFailed`）——否则调用方推游标，整批永久丢失。
- 所有会"推进游标"的入口必须保证持久化成功后才推进；去重撞"空成功"是最大隐性丢数据源，故回滚纪律是铁律。

### 安全 / 健壮性
- **prompt 注入**：`_allm_extract_facts_batch` 用一次性 nonce（`SCOPED_BATCH_SEGMENT_NONCE_BYTES`）作为段边界 token，攻击者消息在 nonce 生成前写死、猜不到；占位符替换顺序 `{LANLAN_NAME}`→`{SEGMENT_NONCE}`→`{SEGMENTS}` 防止正文里的字面占位符被二次替换。
- **LLM 输出不可信**：importance clamp 1..10、entity/source 白名单、段号越界绝不 clamp（A 的内容挂到 B 头上比整批重试严重）、speaker_provenance 只来自调用方、review 输出 content 归一化为 str。
- **防自我强化死循环**：`source='ai_disclosure'` 的 fact 永不进 Stage-2 evidence loop（`signal_processed=True` + source filter 双重防御）。
- **损坏文件降级**：归档文件损坏 → 放弃归档而不是覆盖；损坏 FTS 索引行 → 从 `load_facts_full` 收敛；`safe_importance` 防手改行 TypeError 打穿全角色合成。
- **scoped 跨界防御**：Stage-2 batch 只许 legacy 私聊行；非 legacy 行防御性出队 + `mark_signal_processed`，防占 batch 名额饿死主链路。

### 常见坑（改代码前必读）
1. **不要在临界区内放耗时 LLM 调用**（会挡住 /cache 全链路）。
2. **不要给 LLM 调用加 `temperature`**——gatekeeper CI 会拦。
3. **不要硬编码模型名做回退**——tier 未配置就该让请求失败。
4. **in-place 改既有 fact 前先想回滚**：source 升级/信号翻转失败必须还原，否则重试撞守卫直接丢保存。
5. **review 用新 fingerprint 提交**（patched 后重算），旧指纹在改写后的 history 里永远定位不到。
6. **scoped fact 原文不进日志**（只打域标识 + 长度），防群聊内容泄露到日志。
7. **`semantic_dedup=False` 只豁免 FTS5 语义去重，SHA-256 精确去重永不过**——外迁批也幂等。

---

*报告生成基于本地下载的 NEKO 源码快照（2026-08 前版本）。常量数值以 `config/domain` 实际值为准；本报告中"未下载"标注表示该常量在本地仅见引用、数值无法确认。*

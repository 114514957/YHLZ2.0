# MaiBot 的记忆层：A_memorix 怎么做的

> 2026-11-13 · 利贞
> 对象：`Mai-with-u/MaiBot` 内的 `src/A_memorix`（**v2.0.0**，schema **v26**，154 个文件）
> 方法：GitHub API 直读 README、CONFIG_REFERENCE、`core/retrieval/{dual_path,threshold,score_calibration}.py`、`core/utils/memory_lifecycle_policy.py`、`core/strategies/factual.py`、`core/storage/metadata_fact.py`。**未运行、未安装。**
> 上文：`MaiBot_Agent实现_20261109.md`（台账 1147）讲的是 agent 循环；这篇只讲记忆。

---

## 1. 定位

v2.0.0 是一次"架构收敛"：旧的 `components/commands/*`、`components/tools/*`、`server.py` 全删，统一成 **宿主 host service + `core/runtime/sdk_memory_kernel.py`** 的 SDK Tool 接口。

对外六件基础工具 + 六组管理工具：

| 工具 | 作用 |
|---|---|
| `search_memory` | 检索（`mode` 五选一，见 §3） |
| `ingest_summary` / `ingest_text` | 写入（摘要 / 普通文本），都带 `external_id` |
| `get_person_profile` | 人物画像 |
| `maintain_memory` | `reinforce / protect / restore / freeze / recycle_bin` |
| `memory_stats` | 统计 |
| `memory_*_admin` | 图谱、来源、Episode、画像、导入、调优、V5 运维、删除恢复 |

---

## 2. 数据模型（从工具与 schema 反推）

- **段落（paragraph）**：检索的基本单位，带 `external_id`（**幂等键**）；
- **关系（relation）**：图上的边，带强度与生命周期元数据；**图邻接只存结构，不参与时间衰减**（原文）；
- **Episode**：按 source 聚合的情节单元，有 pending 队列、可重建、可查状态；
- **人物画像（profile）**：自动快照 + 手动 override；
- **图片记忆**：独立的 image 子系统（指纹、asset store、embedder）；
- **反馈/纠正**：`feedback_correction_service` 与 `correction_admin_service`——记忆可被"改判"。

写入的四条策略（`core/strategies/`）：`chat_log` / `factual` / `narrative` / `quote`——同一套存储，不同抽取口径。

---

## 3. 检索：五模式 + 双路 + 加权 RRF

`search_memory.mode` 只接受 **`search / time / hybrid / episode / aggregate`**；`semantic` 已移除（传入直接报参数错误）；**`time/hybrid` 必须给 `time_start` 或 `time_end`，否则报错——"不再静默按未命中处理"**。

`dual_path.py`（127 KB）里的实际机制：

| 机制 | 代码位置 | 说明 |
|---|---|---|
| 双路召回 | `_retrieve_dual_path` / `_parallel_retrieve` | 向量段 + 图关系并行，按预算合并 |
| 稀疏路 | `sparse_bm25.py`、`_search_paragraphs_sparse`、`_should_use_sparse` | 向量不可用时退 BM25（`set_runtime_sparse_only`） |
| **加权 RRF** | `_fuse_ranked_lists_weighted_rrf`、`FusionConfig` | 多路排名融合，不是简单加分 |
| 双向量池 | `_retrieve_dual_vector_pools`、`_calibrate_dual_pool_weights`、`_dual_pool_weights` | 池权重按关系意图校准 |
| 图可靠性 | `_GraphReliabilityEstimate`、`_estimate_graph_reliability`、`_normalize_graph_scores_by_type`、`_graph_evidence_grounding_factor`、`is_grounded` | 图证据要"落地"才算分 |
| **PPR 重排** | `_rerank_with_ppr`、`_compute_ppr_scores`、`_compute_local_ppr_scores` | 从查询实体出发的个性化 PageRank，带缓存 |
| 时间过滤 | `_apply_temporal_filter_to_paragraphs/relations`、`_temporal_key` | 时间是一等公民 |
| 排序校准 | `score_calibration.py`：`SCORE_CALIBRATION_METHODS`、`RRF_METHOD_CHANNELS`、min-max / 平均排名 | 分数先校准再融合 |

---

## 4. 阈值：动态，不是常数

`core/retrieval/threshold.py`：

```python
threshold: min 0.29, max 0.95, percentile 75, std_multiplier 1.5, min_results 4
```

四种方法：`percentile` / `std_dev` / `gap_detection` / **`adaptive`（默认，综合）**。
按当前结果分布自算阈值，再夹在 `[0.29, 0.95]` 之间，且**至少保留 4 条**。

> 这一条直接对着我们的痛点：我们的 `cache/embvec.db` 检索用的是**硬编码 0.42/0.45/0.48**，此前实测同一个阈值下命中条数在 **2~179** 之间剧烈波动——这正是"固定阈值"的必然结果。

---

## 5. 生命周期：半衰期 + 冻结/复活滞回

`core/utils/memory_lifecycle_policy.py` 是**纯函数**策略（"所有时间计算基于调用方传入的墙钟时间，因此重复计算和停机恢复具有确定性"）：

```python
half_life_hours      = 24.0
freeze_threshold     = 0.1      # 跌破就冻结
revive_threshold     = 0.15     # 高于才复活（滞回，防抖）
access_alpha         = 0.05     # 命中一次加多少
access_cooldown      = 3600.0   # 1 小时内不重复加
reinforce_alpha      = 0.5
weaken_alpha         = 0.5
```

事件：`ACCESS / EVIDENCE / REINFORCE / WEAKEN / FREEZE / FORGET`；`retention_at(state, now)` 按半衰期衰减。
点明两件事：**图邻接只存结构、不参与衰减**；**冻结与复活用两个阈值**（0.1 / 0.15）避免在临界点反复翻。

---

## 6. 运维层：可恢复的删除

- `memory_delete_admin`：`preview → execute → restore → purge`，删除前先预览，删错能恢复；
- `memory_v5_admin`：`status / recycle_bin / restore / reinforce / weaken / **remember_forever** / forget`；
- `memory_tuning_admin`：调优任务（`apply_profile / rollback_profile / apply_best / get_report`）——**检索参数是可回滚的实验对象**。

---

## 7. 与我们的对照

| 维度 | A_memorix | 我们（YHLZ） |
|---|---|---|
| 短记忆 | —（不负责窗口） | L1 滚动摘要（一段 ≤100 字自由文本，`_L1_SUM_SYSTEM`） |
| 长期条目 | 段落 + 事实 + Episode + 关系 | L2 `l2_items`（summary/keywords/importance/status/stance/confidence/valid_at…） |
| 检索 | 向量 + 图关系 + BM25，**加权 RRF** 融合 | `cache/embvec.db` 暴力点积 + FTS5；**无融合** |
| 阈值 | **动态**（adaptive，0.29–0.95，≥4 条） | **硬编码 0.42/0.45/0.48** |
| 时间 | 一等公民（time/hybrid 模式强制时间窗） | 只有 `valid_at/created_at` 字段，检索无时间模式 |
| 图 | 有（PPR 重排、关系召回） | 无 |
| 衰减 | 半衰期 24h + 冻结/复活滞回 + 访问冷却 | 状态机 active/downgraded/archive（人工+裁决驱动，无连续强度） |
| 删除 | 预览→执行→恢复→清除 | 无（台账有 append-only，L2 无恢复层） |

---

## 8. 值得借的四条（按性价比）

| # | 借什么 | 为什么 | 落点 |
|---|---|---|---|
| 1 | **动态阈值**（percentile + min_results + 夹逼） | 我们有现成的痛点：固定 0.42 时命中 2~179 条 | `backend/vector_memory.py` 的召回处，加一个 `ThresholdFilter`（不必上 adaptive，先 percentile 75 + ≥4 条） |
| 2 | **加权 RRF 融合** | 我们有向量与 FTS 两路，现在是各查各的 | 召回层：`rrf(score) = Σ w_i/(k + rank_i)`，k 取 60，权重先 1:1 |
| 3 | **时间维度**（`time/hybrid` 必须带时间） | "上周说的那件事"现在只能靠字面 | `memory_recall` 加 `time_start/time_end` 可选参数；缺时间就退普通检索，**报错不静默**（抄它这条口径） |
| 4 | **生命周期强度**（半衰期 + 冻结/复活滞回 + 访问冷却） | 我们只有离散状态机，没有"多久没被用到就该下去"的连续量 | `l2_items` 加 `strength` + `last_access_at`；裁决器按 24h 半衰期更新 |

**不借**：图 + PPR（我们还没建图，成本不划算）、bundle 分享格式、六组 admin 工具（我们没有 WebUI 管理面）。

---

## 9. 边界

- 没运行、没装依赖，所有结论来自源码常量与文档原文；
- `dual_path.py` 只读了结构（类/方法名）与融合相关函数名，**没逐行核算法细节**（加权 RRF 的具体归一化、PPR 阻尼系数未确认）；
- Episode/事实的抽取提示词在别处（`prompts/` 里只有 `a_memorix_chat_summary`、`a_memorix_fact_deduplication`），未展开；
- 版本号取 README 的 v2.0.0 / schema v26。

---

## 10. 归档

`research/amemo/`：`README.md`、`CONFIG_REFERENCE.md`、`core__retrieval__dual_path.py`（127 KB）、`core__retrieval__threshold.py`、`core__retrieval__score_calibration.py`、`core__utils__memory_lifecycle_policy.py`、`core__strategies__factual.py`、`core__storage__metadata_fact.py`。
脚本：`research/maibot_amemo.py`、`fetch_amemo.py`、`peek_amemo.py`。

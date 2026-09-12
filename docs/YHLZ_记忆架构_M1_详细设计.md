# YHLZ 记忆架构 · M1 详细设计

> 2026-09-12 · M1（落地第一步）：**"记准你" + "事实可更新、旧账不丢"**
> 上游：`docs/YHLZ_记忆架构_设计_v2.md`（§3/§7）。本 M1 **只加字段与读写路径**，
> **不碰**统一裁决器（M2）、RRF 检索（M3）、管理闭环/梦境（M4/M5）。

## 0. 目标与非目标
- 目标：Profile（画像）**精确读、永不衰减**；事实可更新且**保留历史**（双时态失效）。
- 非目标（留后续）：自动证据裁决、检索融合、衰减调参、实体图升级、梦境。

## 1. 画像（Profile）判据（三问全 yes）
1. 关于**特定人 / 关系 / 自我**？
2. **稳定**（非一次性）？
3. **"错一次是事故"**？

- **可作画像**：①自我/关系/期待/边界（=现有认知根基 + persona + 内在因，保持最高保护）②**老爹的稳定事实与偏好**（称呼/名字/作息/口味/过敏/忌讳/重要日期/长期目标/价值观/稳定偏好/明确指令）③**关系共识（约定）**。
- **不作画像（→Episodic/KB）**：一次性事件、项目进展、临时状态、情绪片段、通用知识（→KB）、模型推断。

## 2. 分类入口（三入口；优先级 b > c > a）
- **a) LLM 写入时判**：抽取时返回 `kind` 建议 + `confidence`。
- **b) 老爹显式指定**：最高优先，直接 Profile（必要时 `protected`）。
- **c) 高置信规则/模式**：称呼/作息/过敏/忌讳/明确指令等模式 + 高置信。
- 冲突或不确定 → **一律 Episodic**（保守）。

## 3. Schema（`l2_items` 扩展，向后兼容）
| 列 | 含义 |
|---|---|
| `kind` | `episodic`(默认) / `profile` |
| `protected` | 1=永不衰减、不清扫（身份/关系/期待） |
| `valid_at` | 事实生效时间（缺省=created_at） |
| `invalid_at` | 0=仍有效；>0=已失效（**软失效，不删**） |
| `superseded_by` | 被哪条取代（可回滚） |
| `confidence` | 写入/证据置信（0..1；默认 0.5） |

- status 不变（active/cold/archive/downgraded）；"失效"由 `invalid_at` 表达，**不新增 status**。
- 查询"**当前**"：`invalid_at = 0`；查询"**历史**"：不过滤。

## 4. 双时态失效（三档）
- **默认（保守）**：并存 + 记 `supersedes`/`conflicts_with` 关系，**不自动失效**；读取时按 **时间 + confidence** 排序，旧条降权。
- **高置信自动失效**：**同主体 + 同谓词 + 明确否定 + 来源可信（主人/高置信）四条齐** → 旧条 `invalid_at=now`、`superseded_by=新id`（软失效，可回滚）。
- **不确定**：不失效 + **趁机问老爹**。

## 5. 迁移（现有 ~500 条，保守，幂等）
1. 先**快照**。
2. 全部默认 `kind='episodic'`、`valid_at=created_at`、`confidence=0.5`。
3. 仅对**能确定**的标 Profile：来源=老爹 / 明确偏好 / 称呼 / 作息 等（规则；可选 LLM 复核），标 `kind='profile'` + `confidence`。
4. `protected` **只给身份/关系/期待**（不搬 L2；认知根基/persona/drives 本就是 protected）。
5. **不改 summary 文本**；迁移脚本幂等（可重跑）。

## 6. 代码改动点（最小）
- `backend/target_memory.py`：`L2Item` 增字段；`_init_db` 加列迁移；`store_item` 写 `kind/protected/valid_at/confidence`；`recall`/`contextual_recall` 输出 `kind`；新增 `profile_get(key)`（精确读）与 `supersede(old_id,new_id)`（软失效）；**衰减/清扫跳过 `protected`/`profile`**。
- `backend/target_entry.py`：写入侧接入分类（a/b/c）；读取侧 **Profile 优先注入**（`profile_get`）；冲突时"并存 + 排序"。
- `backend/target_scheduler_tools.py`：`memory.save` 支持 `kind`/`lifespan`（默认自动判）。
- 新增能力：`memory.profile`（查画像，owner）；`memory.supersede`（手动失效，owner）。
- 迁移脚本 `tools/memory_migrate_m1.py`（先快照、幂等）。

## 7. 验收（造样例 + 真实场景，结合）
- **样例集**（我造，中文 ~20 条）：跨会话回忆、**事实更新（旧不丢）**、Profile 精确命中、protected 不衰减、**群聊/公开不注入私密画像**。
- **你的真实场景**（2–3 个）。
- 指标：Profile 命中率、**误失效=0**（默认不自动失效）、重启不丢、快照可回滚。
- **真机**：工作台对话验证"记准 / 改口"。

## 8. 风险与降级
- 分类误判 → 默认 Episodic + 不确定不问；可被老爹反向指定。
- 失效误伤 → 默认不自动失效；软失效可回滚。
- 复杂度 → M1 只加字段 + 读写路径，不碰检索/裁决。

## 9. 不做（M1）
RRF/multi-signal、统一证据裁决器自动降权、衰减阈值重调、实体图多跳、梦境引擎。

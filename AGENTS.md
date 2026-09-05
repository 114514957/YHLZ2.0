# YHLZ Agent Rules

## 检索纪律（tool-first）

台账（docs/上下文台账.md）与记忆检索一律走 MCP 工具（`yhlz` server），不亲自读全文/grep：

- 查项目历史、决策、编号、计划 → `yhlz_ledger_search`
- 查用户偏好/记忆条目 → `yhlz_memory_recall`
- 需要当前时间 → `yhlz_system_time`

参考工具：`ledger_search` 用 1-3 个关键词（中文可）；结果含记录号（如 ledger:0148:xxx），引用答案时指出来源记录。

## 台账纪律

- `docs/上下文台账.md` 是唯一事实源；重要决策/结果每次必须追加记录（编号递增）。
- 敏感内容（API key 等）只记指纹，不写明文。

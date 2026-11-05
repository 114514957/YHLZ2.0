# YH Agent Rules

> 总目录：`C:\Users\ACE_WAN——PROJECT\YHLZ`；元亨主路径：`…\YHLZ\YH`，利贞：`…\YHLZ\LZ`。
> `yhlz` MCP serverName / `mcp__yhlz__*` 工具名 / `yhlz_*.py` 模块名保留兼容，不要改。

## 检索纪律（tool-first）

台账（docs/上下文台账.md）与记忆检索一律走 MCP 工具（`yhlz` server），不亲自读全文/grep：

- 查项目历史、决策、编号、计划 → `yhlz_ledger_search`
- 查用户偏好/记忆条目 → `yhlz_memory_recall`
- 需要当前时间 → `yhlz_system_time`

工具名前缀随载体而定，同一批工具：opencode 时代是 `yhlz_*`；**利贞现跑在 harness（DeepSeek
Harness）上，工具名是 `mcp__yhlz__ledger_search` / `mcp__yhlz__memory_recall` /
`mcp__yhlz__system_time`**（ledger 0797）。调用前先按当前工具面里的实际名字选。

参考工具：`ledger_search` 用 1-3 个关键词（中文可）；结果含记录号（如 ledger:0148:xxx），引用答案时指出来源记录。

## 台账纪律

- `docs/上下文台账.md` 是唯一事实源；重要决策/结果每次必须追加记录（编号递增）。
- **做之前必须翻**（2026-11-02 老爹立）：接任务先 `ledger_search` 查 1–3 个关键词，
  确认历史结论、基线数字、踩过的坑。**不凭印象，不凭「我记得」。**
- **记账必读**：记了不读等于没记。翻台账是**回忆自己做过什么**，不是「找新发现」；
  报「新发现」之前先确认这不是自己写过的、做过的。自己铺过的路忘了，那路就等于没铺。
- **报「某能力崩了」之前**：先看**原始输出**（评测 JSON 的 `answer` 字段、程序的真实产物），
  再翻台账找历史基线，最后才下结论。**判分函数的结果 ≠ 实际行为。**
  （2026-11-01 教训：把 gemma 的 `call:name{}` 格式当成"没调工具"，白查一轮。）
- 敏感内容（API key 等）只记指纹，不写明文。

## 命令执行权限

- 用户明确要求（2026-10-15）：所有命令执行走普通 CMD（cmd.exe），不使用管理员模式，不请求提权，不调用 runas。
- 启动子进程同样保持非管理员权限；验证权限时以进程令牌为准。

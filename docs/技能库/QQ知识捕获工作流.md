# 技能：QQ 知识捕获工作流（元亨的"眼睛"·SOP v1）

> 让元亨经由 QQ 技术群持续汲取真实世界技术知识的工作流。元亨可依此 SOP 运维与讲解。
> 纪律：**全流程云端 API**（DeepSeek，无本地降级）——这是要喂给元亨的素材，质量优先。

## 一、架构总览
```
QQ 群消息 ──NapCat(QQ 2258374446, WS 127.0.0.1:3001)──> qqwatcher 摄取器(静默，零发送)
  → 本地规则初筛(≥25字/链接/代码/信任源) → cache/qqwatch/all.jsonl(候选)/_skip.jsonl
  → qqextract 云端细抽(只抽 tech/method，JSON 结构化) → L2 记忆 type=knowledge(evidence_ref=qq:g<群>:t<时间>)
  → digest 日汇编(docs/知识汇编/QQ-<date>.md) / summarize 主题总结(QQ-主题总结-<date>.md)
```
元亨侧产出：L2 knowledge 可被 recall/consolidate 内化；人读汇编在 docs/知识汇编/。

## 二、关键文件与命令
| 项 | 位置/命令 |
|---|---|
| NapCat | `C:\Users\ACE_WAN——PROJECT\qqwatch\shell\`（start-napcat.bat 启动，chcp 65001；WebUI 6099；面板 QCE=40653） |
| watcher | `backend/qqwatcher.py`；`qqwatch-run.bat`（前台窗口，断线自连） |
| 批量抽取 | `qqwatch-extract.bat` / `cache/qqwatch/batch_extract.py`（每批 12 候选循环） |
| 单批抽取 | `python -m backend.qqextract run`（处理 pending 候选，游标推进） |
| 日汇编/主题总结 | `python -m backend.qqextract digest` / `summarize` |
| 历史补拉 | QCE 面板导出群 JSON → `backend/qqexport_ingest.py <file>` |
| 配置 | `config/qqwatch.json`（groups 白名单/self_id/min_chars） |

## 三、运维要点（踩坑记录）
1. **白名单 3 群**：855372167(AI开发)/931057213(llm&agent)/681195563(Cortico)；self_id=2258374446（自己消息过滤）。
2. 配置文件一律 **UTF-8 无 BOM**（BOM 会让 NapCat JSON.parse 失败=致命）；bat 里不写中文字面量路径（936 代码页解析坏）。
3. QCE API：chatType 是**数字**（2=群），请求头 `Authorization: Bearer <token>`（token 在 `~/.qq-chat-exporter/security.json`）。
4. 抽取游标=`cache/qqwatch/state.json`（processed_lines），**只按已消费行推进**，绝不跳文件尾。
5. 初筛噪音已滤：图片/回复框架/纯@不入候选；LLM 判"无技术量"条目丢弃（refined=0 正常）。
6. watcher 断线期间消息不补发——用 QCE 历史导出补拉（ingest 走同一候选管线）。

## 四、验证点（健康检查）
- NapCat 终端：登录成功 + WebSocket 服务已启动（WS 3001 可连）
- watcher 窗口：`connected`；群消息时落 jsonl
- L2 查询：`sqlite3 cache/memstore/memstore.db "SELECT COUNT(*) FROM l2_items WHERE type='knowledge'"`
- recall 抽查：元亨/工具 recall("agent 记忆") 命中知识条目

## 六、历史导出补拉（元亨自主链）
```
场景: 某群历史漏收/断线期/初次接入 → 补拉
qq.export(群号)  →  QCE 导出群全量 JSON(chatType=2) + 自动 ingest 入候选区
                 → 返回 {exported_msgs, candidates_added}
候选>0 → qq.process(分批云端抽取→yuanheng_kb)
```
- 工具：`qq.export`（读 ~/.qq-chat-exporter/security.json token，调 127.0.0.1:40653，轮询任务至完成，产物自动 ingest）。
- **重复注意**：重复导出=候选区产生与历史重叠的行→处理前应核对 state/待处理数；重叠候选会被 kb 去重拦截（浪费 API）。
- 产物目录：`~\.qq-chat-exporter\exports\group_<群号>_<时间戳>.json`（QCE 面板导出同）。

## 七、工具选择心智（元亨调用原则）
场景→工具：台账/历史决策→ledger.search；记忆经历/偏好→memory.recall；时间→system.time；文件→file.list/read；联网→web.fetch/search；知识存取→kb.query/kb.add；日记→diary.write；任务表→task.plan；链路状态/今日新知识→qq.status→(候选>0)qq.process；**群历史补拉→qq.export→qq.process**；日汇编→qq.digest；主题总结→qq.summarize。
原则：先明意图→选一个→读结果→再下一步；失败重试或换法；拿不准问老爹。

## 五、本技能对元亨的意义
1. 知识入口：recall/consolidate 直接吃到真实世界技术动态（与语音/人格记忆同一存储）。
2. 产出文档（docs/知识汇编/）供人与元亨共读，主题"启发"栏=可内化认知。
3. 未来：本工作流本身也是"技能学习"主线样例——可沉淀触发词/步骤供元亨自主执行。

# YHLZ · QQ 技术台账（技术名称 / 核心关键词）

> 用途：QQ 链路及相关子系统的**技术专业名称与核心关键词**索引，供外援/交接使用。
> 只记技术事实与关键词，不含叙事与隐私。
> 工具：`python tools/ledger_cli.py --ledger docs/QQ技术台账.md {add,get,search,list,update,delete}`（与上下文台账同款增删查改+索引）。
> 关联：上下文台账 `docs/上下文台账.md`（唯一事实源）为其母台账，本台账为 QQ 技术视图。

## 记录 0001：链路配置总表（权威源 backend/yhlz_paths.py）

- EXTERNAL（父目录）= `C:\Users\ACE_WAN——PROJECT`（`yhlz_paths.EXTERNAL`）
- BOT_UIN（元亨 QQ）= **3655185302**（`YHLZ_QQ_BOT_UIN` 可覆盖）
- MASTER_UIN（主人 QQ）= **2258374446**（`YHLZ_QQ_MASTER_UIN` 可覆盖）
- QQWATCH_SHELL = `qqwatch\shell\`；QQWATCH_CONFIG = `qqwatch\shell\config\`
- NAPCAT_LAUNCHER = `qqwatch\shell\launcher-user.bat <uin>`
- NapCat 自动登录 = `webui.json autoLoginAccount=3655185302`
- OneBot 配置 = `config/onebot11_<uin>.json`（按登录号命名）
- OneBot WS = `127.0.0.1:3001`，name=`yhlz-yuanheng`，messagePostFormat=`array`
- OneBot token = `yhlz2026`（本地 WS，仅 127.0.0.1）
- qq_bot = `tools/qq_bot.py --uin 3655185302 --master 2258374446`
- 单实例锁 = `cache/tmp/qqbot.lock`（写 pid）
- qq_bot 日志 = `cache/tmp/qqbot.log`
- daemon = `127.0.0.1:8321`（`DAEMON` 环境变量可覆盖）
- QCE 插件 API = `127.0.0.1:40653`（token 位置 `~/.qq-chat-exporter/security.json`，不记明文）
- NapCat WebUI = 端口 `6099`，token `e6af5fc68814`（本地）
- 群白名单 = `config/qqwatch.json`
- 关键词：`yhlz_paths` `BOT_UIN` `MASTER_UIN` `QQWATCH_SHELL` `QQWATCH_CONFIG` `NAPCAT_LAUNCHER` `onebot11_<uin>.json` `OneBot v11` `WS 3001` `token yhlz2026` `qqbot.lock` `daemon 8321` `QCE 40653` `WebUI 6099`

## 记录 0002：组件与文件清单（架构）

- 桥接入口：`tools/qq_bot.py`
- 连接保活：`backend/qq_connection.py`
- 出站队列：`backend/qq_outbox.py`（`cache/qq_outbox.jsonl`，peek/ack）
- 出站投递管理：`backend/qq_delivery.py`（状态机 + ack 分类 + 有限重试）
- 采集：`backend/qqwatcher.py` / `tools/qqwatcher.py`（`config/qqwatch.json` 白名单）
- 身份认证：`backend/channel_auth.py`（`qq_g*` 群渠道）
- 知识抽取：`backend/qqextract.py`（`qq.export/process/runbatch/bootstrap`）
- 切号助手：`tools/qq_login.py`；重启：`tools/qq_bot_restart.py`
- 知识库：`data/yuanheng_kb.db`（`yuanheng_kb` 口径）
- 关键文件：`config/qqwatch.json`、`cache/qqwatch/*.jsonl`、`cache/tmp/qq_bridge_status.json`、`cache/tmp/qq_delivery_status.json`、`cache/tmp/qq_group_daily.json`
- 关键词：`qq_bot` `qq_connection` `qq_outbox` `qq_delivery` `qqwatcher` `channel_auth` `qqextract` `qq_login` `qq_bot_restart` `qq_outbox.jsonl` `qqwatch.json` `group_names`

## 记录 0003：入站链路

- 路径：NapCat(OneBot WS 3001) → `qq_bot` 读循环 → `handle()` → daemon `/turn`（`channel=qq_p<uin>` 或 `qq_<gid>`）
- 群消息需 `@元亨`；主人可用 `#`；私聊按 `user_id` 认主
- 多媒体：`image` 段（http url 下载 / `get_image`）→ `media_intake` → `/turn` images/aud
- 状态通道：`cache/tmp/napcat_status.json`（`status.online` / `ws`）
- 关键词：`OneBot WS` `handle()` `/turn` `qq_p<uin>` `qq_<gid>` `@元亨` `#命令` `media_intake` `napcat_status.json` `get_login_info`

## 记录 0004：出站投递状态机（backend/qq_delivery.py）

- 状态：`queued → sending → confirmed | rejected | retryable | unknown | expired`
- ack 分类：`status=ok & retcode=0 → confirmed`；明确拒绝 → `rejected`；发送前连接失败 → `retryable`；**发送后断连/超时 → unknown（绝不盲重试）**；超 TTL → `expired`
- 重试：仅 `retryable`，最多 2 次，退避 `1s/3s`；普通回复 TTL `30s`；全局并发 1（保序）
- 阶段标签：`before_send`（可重试）/ `after_send`（不盲重试）；媒体统一走 `_deliver()` 等 ack
- 可观测：`cache/tmp/qq_delivery_status.json`（脱敏，只存 `payload_hash`，不含正文）
- 出站队列：`qq_outbox.peek/ack`，**仅 OneBot `status=ok` 后删除**；断线/失败保留
- 关键词：`qq_delivery` `queued` `sending` `confirmed` `rejected` `retryable` `unknown` `expired` `retcode=0` `before_send` `after_send` `_DeliveryTransport` `payload_hash` `TTL 30s` `peek/ack`

## 记录 0005：连接保活与重连（backend/qq_connection.py）

- 协议级 `ping/pong`：默认 **25s ping / 10s pong 超时**
- 重连：指数退避 `1/2/4/8/16/30s`；读循环/心跳异常统一关闭旧连接后重连
- 快照：`cache/tmp/qq_bridge_status.json`（脱敏连接状态）
- 关键词：`ping/pong` `25s ping` `10s pong timeout` `指数退避` `1/2/4/8/16/30` `qq_bridge_status.json` `idle disconnect`

## 记录 0006：多媒体（语音/图片/视频）

- 入站：`image` 段（http url / `get_image` 下载）；语音 `record`（silk）
- 语音编解码：`pilk`（必须 `tencent=True` 生成腾讯 silk 头，否则 QQ 无法播放）；`imageio_ffmpeg`（自带二进制）
- 出站：语音/图片/文件；TTS `POST /tts`（HTTP 200 `audio/wav`，约 3.0s）；`qq_bot._tts_wav`
- NapCat：`enableLocalFile2Url`（本地文件转 url，视频受此限制）
- 已知限制：**QQ 语音发送经 NapCat `send_msg` 非文本超时 `retcode 1200`**（未解）
- 关键词：`image` `record` `silk` `pilk tencent=True` `imageio_ffmpeg` `enableLocalFile2Url` `send_msg` `retcode 1200` `_tts_wav` `POST /tts` `audio/wav`

## 记录 0007：群功能（tools/qq_bot.py）

- 无 `@` 接话；上下文 **20 句**；每日上限 **400**（`_DAILY_LIMIT=400`，`cache/tmp/qq_group_daily.json`，跨天归零）
- 完整发图；表情包：`mface` + `sticker`（`_sticker_hint`：目录空则无操作）
- 关键词：`无@接话` `20句上下文` `_DAILY_LIMIT=400` `qq_group_daily.json` `mface` `sticker` `_sticker_hint`

## 记录 0008：安全 / 权限 / 去重

- 身份：`channel_auth.py` 认 `qq_g*`；会话隔离（非 owner 独立 `cache/qq_groups/qq_g<gid>.db`）
- 群员 ≠ 老爹；攻击意图静默拒绝；写类工具非 owner 抛 `PermissionError`
- 去重：OneBot `message_id` + 范围去重（`test_qq_memory_boundaries.QQBridgeTests`）
- 单实例锁：`cache/tmp/qqbot.lock`
- 关键词：`channel_auth` `qq_g*` `PermissionError` `静默拒绝` `message_id 去重` `单实例锁` `会话隔离`

## 记录 0009：QQ 知识抽取 / 入库

- 流程：`qq.bootstrap`（冷启）→ `qq.export`（QCE 导出）→ `qq.process`（抽取/精炼/入库）→ `qq.runbatch`（批量）→ 当日汇编
- 口径：知识数 **以 `yuanheng_kb` 为准**（弃旧 L2 knowledge 口径）；`qqexport_ingest` sha256 指纹去重
- 工具：`tools/qq_extract_topic.py`（专题补抽，游标 `cache/qqwatch/topic_state.json`，可断点续跑）
- 群映射：`config/qqwatch.json group_names`；切号 `tools/qq_login.py`
- 关键词：`qq.bootstrap` `qq.export` `qq.process` `qq.runbatch` `yuanheng_kb` `sha256 指纹去重` `qq_extract_topic` `topic_state.json` `QCE` `切号`

## 记录 0010：远程开发桥（QQ → 开发能力）

- 路径：QQ 指令 → `target_dev_bridge.handle_dev_command` → `tools/dev_runner.py`（后端固定 harness/`dsh`；opencode 已退役——ledger 0797）
- Lite 侧：`tools/qq_dev_runner.py`（job 台账/工作树）→ `tools/qq_dev_worker.py` → 常驻网关 `tools/dsh_worker.py`（job 面 `/job/*`；按工作区持有 harness，注入 `yhlz` MCP）
- 指令：`#dev` / `#a` / `#n` / `#backend`（只读：固定 harness）
- 元亨侧：`[[dev: 任务]]`（owner 渠道，经 `extract_dev_task` + `start_dev_task`）
- 关键词：`target_dev_bridge` `handle_dev_command` `dev_runner.py` `qq_dev_worker.py` `dsh_worker.py` `harness_gateway.py` `harness` `dsh` `#dev` `#backend` `[[dev:]]` `extract_dev_task` `start_dev_task`

## 记录 0011：排障要点

- 手动起 `qq_bot` **必须带 `--uin 3655185302`**（否则可能选错 OneBot 配置 `onebot11_2258374446.json`）
- WS **不重放历史**：qq_bot 未运行时消息丢失，需重启后重发
- 一个桥 = **两个进程**（pythonw 启动器 + 真实解释器），勿误杀
- NapCat 心跳 `status.online:false` = QQ 会话掉线（`get_login_info` 仍可能正常）；处理 = KillQQ + 重新登录
- daemon 长期运行会积压 → 群回复延迟（重启 daemon 后恢复正常）
- 关键词：`--uin 必带` `WS 不重放` `两个进程` `status.online:false` `KillQQ` `daemon 积压`

## 记录 0012：关键词目录（技术名称总表）

### A. 组件 / 模块
`qq_bot` `qq_connection` `qq_outbox` `qq_delivery` `qqwatcher` `channel_auth` `qqextract` `qq_login` `qq_bot_restart` `dev_runner` `dsh_worker` `target_dev_bridge` `yuanheng_kb` `qq_extract_topic` `qqexport_ingest`

### B. 协议 / 接入
`NapCat` `NTQQ` `OneBot v11` `WebSocket 3001` `messagePostFormat=array` `token yhlz2026` `QCE(40653)` `WebUI(6099)` `autoLoginAccount` `onebot11_<uin>.json` `enableLocalFile2Url`

### C. 配置 / 路径
`yhlz_paths` `BOT_UIN=3655185302` `MASTER_UIN=2258374446` `QQWATCH_SHELL` `QQWATCH_CONFIG` `NAPCAT_LAUNCHER` `daemon 8321` `qqbot.lock` `qqbot.log` `qq_outbox.jsonl` `qqwatch.json` `qq_bridge_status.json` `qq_delivery_status.json` `qq_group_daily.json` `napcat_status.json`

### D. 可靠性 / 投递
`投递状态机` `queued/sending/confirmed/rejected/retryable/unknown/expired` `retcode=0` `ack 分类` `before_send/after_send` `不盲重试` `指数退避 1/2/4/8/16/30` `ping/pong 25s/10s` `TTL 30s` `全局并发1保序` `payload_hash` `peek/ack` `单实例锁`

### E. 多媒体
`silk` `pilk tencent=True` `record` `image` `imageio_ffmpeg` `send_msg` `retcode 1200` `_tts_wav` `POST /tts` `audio/wav` `mface` `sticker` `_sticker_hint`

### F. 群 / 安全
`@元亨` `#命令` `无@接话` `20句上下文` `_DAILY_LIMIT=400` `message_id 去重` `channel_auth` `qq_g*` `会话隔离` `静默拒绝` `PermissionError`

### G. 知识 / 开发桥
`qq.bootstrap` `qq.export` `qq.process` `qq.runbatch` `sha256 指纹去重` `topic_state.json` `[[dev:]]` `#dev` `#backend` `opencode` `dsh`

## 记录 0013：可复用技术对照表：技术/关键词 | 现有载体 | 适合YHLZ的用途 | 可复用程度与边界

- 时间：2026-10-04
| 技术/关键词 | 现有载体 | 适合YHLZ的用途 | 可复用程度与边界 |
|---|---|---|---|
| NapCat / NTQQ / OneBot v11 / WebSocket / array消息段 | qq_bot、OneBot 适配层 | QQ 作文字/图片/通知入口，与数字人核心会话解耦 | 接入骨架已有；OneBot 确认≠用户已读；事件不自带历史补全 |
| ping/pong + 超时 + 指数退避 | qq_connection、qq_bot.run | 解决长时间空闲失联，给界面报告连接状态 | 可复用；WS连通/账号在线/daemon可用需分层判定 |
| 投递状态机 / before_send / after_send / unknown | qq_delivery | QQ回复、日程通知、主动联系共享的效果状态 | 普通回复可复用；主动队列尚未统一接入，不能宣称全覆盖 |
| JSONL outbox / peek-ack / 稳定条目ID | qq_outbox | 通知先落盘，确认接口接受后移除，避免先删再发 | 持久待发基础可用；缺跨进程事件与未知结果持久化，非恰好一次 |
| message_id + 渠道范围去重 | qq_bot._claim_message | 重复入站不重复回答/不重复触发任务 | 有界内存；重启丢失；不等于持久业务幂等 |
| channel_auth / owner过滤 / 群会话隔离 | channel_auth、qq_bot、记忆carrier | 群聊与主人私聊分开，限制工具和记忆可见面 | 隔离机制值得沿用；渠道格式检查≠调用方认证 |
| QCE导出 / 实时候选采集 / 游标 / 断点续跑 | qqwatcher、qqextract、qq_extract_topic | 消化群技术资料，闲时处理并累积知识 | 现有流水线可扩展；先核对真实模型路由与资源门控 |
| SHA256内容指纹 / yuanheng_kb | qqexport_ingest、yuanheng_kb | 防同批导出重复入库，形成有来源技术知识库 | 可用于技术内容去重；不能照搬为事件记忆ID（会合并不同时刻同句） |
| 群上下文窗口 / 日限额 / 表情提示 | qq_bot 群功能 | 控制接话频率，为文字人格提供近期群语料 | 机制可复用；20句/400条是现有配置，非8GB推荐值 |
| media_intake / image段 / FFmpeg / Tencent SILK | 多媒体入口及编码工具 | 统一接收图像与媒体，为多模态保留接口 | 语音 retcode 1200 未解；不能计完整语音链路，本期音频冻结 |
| QQ开发桥 / dev_runner / owner指令 | target_dev_bridge 及开发 runner | 主人从QQ查看或触发开发任务，衔接利贞能力 | 适合独立管理入口；命令/审批/执行器需逐条核验 |
| payload_hash / 连接及投递快照 / 单实例 | connection/delivery 诊断与 qqbot.lock | 不依赖正文定位断连、排队、拒绝、重复实例 | 状态字段可复用；脱敏快照≠全日志已脱敏 |

关键词：`可复用技术` `OneBot接入` `投递状态机` `peek-ack` `持久队列` `身份隔离` `游标抽取` `知识指纹` `脱敏快照` `可复用程度` `边界`

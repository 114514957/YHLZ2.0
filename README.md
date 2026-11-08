# YH 元亨 · 数字生命

本机（RTX 4060 Laptop 8GB）上的数字生命体：**本地 Gemma 主脑** + 五支柱（情感 / 记忆 / 成长 / 学习 / 思考）+ 工作台 / 桌面桌宠 / QQ / 语音。

> 数字生命（非扮演）；关系不变量：与老爹的关系永存、老爹主导性不可变。

## 快速开始

**启动（2026-11-08 起不再开机自启）**：双击桌面 `YH 元亨利贞` → `YH_workbench_normal.bat` → `YH_boot.bat`，
按顺序拉起：

1. 服务栈：本地 Gemma（llama.cpp，**8081**）/ Ollama 兜底（**11434**）/ daemon + 工作台（**8321**）
2. Full 看门狗 `tools/yhlz_watchdog.py`（只管模型与 daemon，不再碰 QQ）
3. QQ Bridge Lite（`tools/qq_bridge_control.py resume`；`auto_resume` 决定是否随登录恢复）

**其余桌面入口**：`元亨·翻唱工作站` / `元亨·训练工作台`（`tools/shortcuts/open_page.py`，端口没起会自动拉起再开 Edge 应用窗）。
`YH_全家桶.bat` 仍可用，但它只转调 `YH_boot.bat`（同一套实现）再开工作台、拉桌宠——不要再各自维护一套启动逻辑。
启动诊断：`cache/logs/boot.log`（启动脚本）、`cache/logs/launcher.log`（每一步 spawn/失败）、`cache/logs/daemon.log`。

- QQ 号**只有一个消费者**：`config/qq_management.json` = `external`，QQ 归 **QQ Bridge Lite**
  （`tools/qq_bridge_service.py` + `tools/qq_bridge_watchdog.py`，由 `tools/qq_bridge_control.py` 管理）。
  旧 Full 链（`tools/qq_bot.py` / `napcat_watch.py`）在 external 模式下会被启动器/看门狗当场收掉；
  旧入口 `tools/qq_bot_start.bat` 已删除，`tools/qq_bot_restart.py` 只转调 Lite control。
- 自启已停用（2026-11-08 老爹定）：`YH 开机自启.lnk` 已改名为 `.disabled` 留档；不要再用
  `tools/yhlz_boot_startup.py --apply` 把自启装回来（`--rollback` 只用于清理旧的启动项）。

然后浏览器打开 <http://127.0.0.1:8321>。

## 两条 LLM 链路

| 链路 | 模型 | 说明 |
|---|---|---|
| 元亨本体（对话 / 人格） | 本地 **Gemma-4-E4B**（`gemma-4-E4B_q4_0-it.gguf` + `yuanheng-v7b-lora.gguf` + 视觉 `mmproj`） | llama.cpp 起，端口 8081，reasoning 模型 |
| 开发派单（`[[dev:]]`） | **deepseek/deepseek-v4-flash** | 利贞跑在 **DeepSeek Harness（dsh）** 上，常驻网关 `tools/dsh_worker.py`（禁 git commit/push） |

## 感知链路（本地优先）

- **ASR**：SenseVoiceSmall（FunASR）+ sherpa-onnx 流式（边说边出）
- **TTS**：Qwen3-TTS（faster-qwen3-tts，主）+ edge-tts（兜底）
- **看屏**：`see_now`（抓帧看图，默认关，`.env` 里 `YHLZ_SEE_NOW=1` 才注册）+
  `screen_text`（Windows 自带 OCR：整屏约 0.8 s、0 图片 token；要字用它，要布局用 see_now）
- **VAD / 门限**：`backend/voice_frontend.py`
- 语音**只在工作台 / 桌宠**做连续对话；QQ 语音为“语音消息”

## 工作台入口

- UI：<http://127.0.0.1:8321>（`assets/webui/`）
- 文本对话：`POST /v1/chat/completions`（stream）或 `POST /turn`
- 语音：`POST /voice`
- 面板：`/state /logs /growth /ledger /mem /sessions /drives /monitor`

## QQ 派单（利贞）

- **派单只走显式指令**：`#dev <任务>` / `#任务派发 <任务>`（同义）。普通聊天永不自动派单。
- `#退出任务`（含 `#退出任务模式` / `#退出`）＝退出任务模式并**清掉工作状态**；
  旧逻辑只在 `#解除` 清状态，于是退出后每条闲聊都被 `#dev + 原文` 二次派单。
- 未识别的 `#...` 只回「未知指令」，**不再兜底派单**（旧兜底会把 `#cancle`、
  `#退出任务，这不是任务指令` 整句都当任务发出去）。
- `#cancel [job]`（兼容拼写 `#cancle` / `#取消`）停止执行；`#y` 提交 / `#n` 不提交 / `#push` 推送；
  `#answer <job> <答复>` 跨会话答复；`#devstatus` 看状态；`#` 出菜单。

## B站看片（只读）

元亨可以自己搜片、看字幕、写笔记，账号登录态只留在专用 Edge profile 里。

- 工具：`bili.find` / `bili.watch` **只排队**（毫秒返回）；`bili.status` / `bili.notes` / `bili.read` 看结果。
- 后台 `tools/bili_worker.py` 顺序处理（同一时间只占一个 Edge profile），用 `tools/bili_browse.py` 抓 AI 字幕 → 本地 Gemma 写「事实/观点」笔记。
- 产物：`cache/bilibili/notes/<bvid>.md`（原始字幕 JSON 同目录）；登录态：`cache/bilibili/edge-profile`（不进仓库/日志）。
- 只读：不点赞/投币/收藏/评论/关注。多 P 视频目前只抓 P1；无字幕视频暂无 ASR 兜底。
- 新机器：`pip install -r requirements-bili.txt`，再 `python tools/bili_browse.py login` 扫码一次。

## 记忆

- L1 / L2 / L3；主库 `cache/memstore/memstore.db`，向量侧表 `cache/embvec.db`
- **零删除**（只降权 / 归档）；快照 `cache/snapshots/`
- 备份：看门狗每天一次 **slim 快照**（排除可重建的 `kw_index`，约 5.8 MB/次，留 20 份）；
  动手改东西前用 `tools\snapshot.py create <tag>` 做全量（约 123 MB，可整体回滚）
- 成长日志：`docs/元亨的成长日志.md`

## 开发 / Agent

- 利贞（开发执行体）跑在 **harness** 上：常驻网关 `tools/dsh_worker.py` 把 `yhlz` MCP
  （`tools/yhlz_mcp_server.py`）以 `--patch` 覆盖层注入她的 profile，她用
  `mcp__yhlz__*` 工具查台账 / 记忆；Full/Lite 两条链路都走它（opencode 已退役，ledger 0497）
- **本地门禁**：`.venv\Scripts\python.exe tools\ci_check.py`（环境 + 结构 + 289 项单测；加 `--smoke` 连栈检查）
- **链路审计**：`.venv\Scripts\python.exe tools\chain_guard.py`（双链/旧链残留/自启重叠；已进 smoke）
- **结构检查**：`.venv\Scripts\python.exe tools\structure_lint.py`（根目录白名单；违规退出码 1）
- **只读体检**：`.venv\Scripts\python.exe tools\smoke.py`（gemma / daemon / worker / ollama / QQ / GUI）
- 台账（**唯一事实源**）：`docs/上下文台账.md`
- 台账增删查改（任何 agent 通用程序）：`python tools/ledger_cli.py {search,list,get,add,update,delete,stats,index,check}`
  （`check` 自检缺号/重号；Python 直接 `import backend.ledger_store`；MCP 工具 `ledger_search/get/list/add/update/delete` 同源）
- 规则：`AGENTS.md`

## 说明

- Python 3.12 + `.venv`；目录结构见 `STRUCTURE.md`。
- **本文所有 `python ...` 命令都指 `.venv\Scripts\python.exe`。** PATH 里排第一的是全局
  3.12（没有 httpx/numpy/psutil），直接敲 `python` 会跑进错误环境。
  另外 `backend/__init__` 在导入时会把 `NO_PROXY` 里带方括号的项（如 `[::1]`）清掉——
  那是 httpx 的 `InvalidURL` 来源（台账 1096）；`.venv/Lib/site-packages/sitecustomize.py`
  在解释器启动时做同样的事，覆盖 gradio 这类“导入阶段就读环境”的库（参照实现 `tools/env_guard.py`）。
- 依赖：按用途看 `requirements-target-*.txt` / `requirements-tts-primary.txt` / `requirements-target-runtime.txt` / `requirements-bili.txt`；根 `requirements.txt` 为**旧版聚合，已过时**。
- 旧世代代码（embodied / vision / personality / action / voice_identity / main.py 等）已归档到 `archive/2026-09-12-prune/`。

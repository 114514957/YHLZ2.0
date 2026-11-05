# YH 项目结构

> 更新：2026-11-05（对照台账重建，记录 1096–1100）。上一版 2026-10-21（台账 0957）；
> 再上一版 2026-09-24（0496）、2026-09-12（0295）。
> 结构债清单与改进计划见 `docs/架构债清单与改进计划_20261021.md`；本文与它冲突时以台账最新记录为准。

## 定位

本机数字生命体：本地 Gemma 主脑 + 记忆 / 成长 / 学习 / 思考 + 工作台 / 桌宠 / QQ / 语音。面向 RTX 4060 Laptop 8GB。

## 三区划分（判断一个模块属于哪区，先看这里）

| 区 | 判据 | 位置 |
|---|---|---|
| **live** | 被 `YH_boot.bat` → `tools/yhlz_launcher.py` / `tools/yhlz_watchdog.py` / `tools/qq_bridge_service.py`、`backend/target_daemon.py`（8321）、`tools/qq_bot.py`、`tools/yhlz_mcp_server.py` 的 import 图可达 | `backend/`（除下表所列）、`tools/`、`assets/`、`desktop/` |
| **测试专用（test-only）** | 只被 `backend/test_*.py` 或 `tools/*eval*.py` 引用，live 链不可达 | 例：`tools/memory_eval.py`、`tools/ab_chat.py`、`tools/llm_compare.py`、`tools/style_ab.py` |
| **归档（archive）** | live 与最小编译检查都不需要 | `archive/` |

新增/删改模块时按此三区自检；落进 archive 的模块不再维护，只在考古时读。

## 根目录规矩（2026-11-05 立）

根目录只允许四类东西：

1. **入口脚本**：`*.bat` / `*.cmd`（YH_* / YHLZ_* 转发壳 / start_* / 登录NapCat 等）；
2. **顶层文档**：`README.md` / `STRUCTURE.md` / `AGENTS.md`；
3. **依赖清单**：`requirements*.txt`；
4. **环境文件**：`.env*` / `.gitignore`；外加 jieba 的生成缓存 `jieba.cache`。

其余一律归位：报告 → `docs/报告/`；研究/调研 → `docs/研究/`；脚本 → `tools/`；
静态资源 → `assets/`；运行时产物 → `cache/`；退役物 → `archive/`。
`tools/structure_lint.py` 按白名单做机器检查（退出码 1 = 有违规），已接进 `ci_check.py`。
测试的 `tempfile.mkdtemp()` 统一落到 `cache/tmp`（`backend/__init__` 在 unittest 下重定向），
不再往根目录扔 `tmp*`。历史上 `web/live_output/player.html` 已挪到 `assets/live_output/`。

## 入口

| 入口 | 说明 |
|---|---|
| `YH_boot.bat` | **唯一开机自启**（启动项 `YH 开机自启.lnk`）：服务栈 → Full 看门狗 → QQ Lite `resume` |
| `YH_workbench_normal.bat` | 手动启动工作台（普通权限守卫，拒绝管理员令牌） |
| `YH_全家桶.bat` | 兼容入口：转调 `YH_boot.bat` + 开工作台 + 桌宠 |
| `start_yuanheng.bat` | 2026-10-22 重建的启动入口包装（旧链丢失后补的）；`启动元亨.bat` 是它的中文别名 |
| `tools/yhlz_launcher.py` | 确保 ollama(11434) / gemma(8081) / daemon+UI(8321)；external 模式顺手收旧 QQ 链残留 |
| `tools/yhlz_watchdog.py` | 自愈看门狗（单实例锁）；external 模式每个 tick 收旧 QQ 链，不碰 QQ |
| `tools/qq_bridge_control.py` | QQ Lite 整链管理：status/start/stop/restart/resume（NapCat→watchdog→bridge） |
| `backend/target_daemon.py` | 常驻 daemon，端口 **8321**（工作台 UI + API） |
| `backend/console_server.py` | 工作台 HTTP 处理器（`ConsoleHandler`，被 `target_daemon._Handler` **继承**后叠加路由；不是死代码） |

### 路径与兼容壳（2026-10-22）

- 总目录：`C:\Users\ACE_WAN——PROJECT\YHLZ`；元亨真实目录：`…\YHLZ\YH`；利贞：`…\YHLZ\LZ`。
  没有 junction；脚本里的 `YH` 就是这一层目录名。
- 6 个 `YH_*.bat` 是正式入口；6 个 `YHLZ_*.bat` 是**转发壳**，只为旧快捷方式存活。
  新脚本一律用 `YH_*`，不要再往 `YHLZ_*` 里加逻辑。

## 端口与常驻

| 端口 | 归属 | 说明 |
|---|---|---|
| 8081 | Gemma（llama.cpp） | 生产模型 `gemma-4-E4B_q4_0-it.gguf` + `yuanheng-v7b-lora.gguf` + `mmproj`，`-c 8192` |
| 8321 | daemon + 工作台 | `/state /monitor /logs /mem /docs …`；`/v1/chat/completions` 兼容口 |
| 8347 | dev worker | 元亨的 QQ 派单网关（`tools/dsh_worker.py`），按需起 |
| 3001 | NapCat OneBot WS | QQ 链；未登录时没有监听 |
| 11434 | Ollama（可选） | `YHLZ_START_OLLAMA` 默认关，launcher 不再拉起 |
| 8090 | llm_workbench | 训练/评测开发台（`llm_workbench/server.py`），按需起 |
| 8348 | **利贞链路**（不属 YH） | `LZ\tools\lz_link.py`，LZ 自己的 .venv 与日志 |

## 健康、门禁与备份（2026-11-05 新增）

| 工具 | 用途 |
|---|---|
| `tools/smoke.py` | 只读体检：gemma / daemon / worker / ollama(可选) / QQ / GUI；FAIL 才算挂 |
| `tools/ci_check.py` | 本地门禁：环境检查 + 结构检查 + 核心 16 模块 177 项 + 记忆 8 模块 102 项；`--smoke` 连栈 |
| `tools/structure_lint.py` | 根目录白名单检查（入口/文档/依赖/环境之外的都算违规） |
| `tools/memory_index_audit.py` | 记忆投影审计 / 重建（`audit` / `rebuild-keyword` …），默认只读 |
| `tools/memory_drain.py` | L1→L2 摘要积压显式排空（默认 dry-run，`--apply` 才写） |
| `tools/snapshot.py` | 全量快照（认知/人格/风格/内在因/实体图/memstore/embvec/kw） |
| `tools/env_guard.py` | 清 `NO_PROXY` 方括号项；`.venv` 的 `sitecustomize.py` 在解释器启动时做同样的事 |
| `tools/ledger_cli.py check` | 台账编号自检（缺号/重号/顺序） |

备份策略（2026-11-05 起）：看门狗每天过一次 **slim 快照**（排除可重建的 `kw_index`，约 5.8 MB/次，
保留 20 份），**不受自主开关影响**；全量快照用于动手前，约 123 MB。

## 核心 backend（live 链）

| 模块 | 职责 |
|---|---|
| `target_daemon.py` | daemon 生命周期、调度、autonomy、记忆维护、HTTP 路由 |
| `target_entry.py` | 一轮对话编排、工具注入、身份 / 规则、派单 |
| `target_orchestrator.py` / `llm_stream.py` | LLM 流式、上下文压缩（mid-loop compaction） |
| `target_memory.py` | L1/L2/L3 记忆、显著度 / 衰减、召回 |
| `target_chain.py` / `target_sherpa_asr.py` | 语音链、sherpa-onnx 流式 ASR |
| `intrinsic_drives.py` | 内在因（好奇 / 渴望 / 期待） |
| `entity_graph.py` / `associations.py` / `communities.py` / `memory_judge.py` / `reflection.py` | 实体图 / PPR 激活扩散 / 社区摘要 / 冲突裁决 / 主动反思 |
| `growth_log.py` / `snapshots.py` / `qq_outbox.py` / `qq_token.py` | 成长日志 / 快照回滚 / 主动联系 / QQ token |
| `voice_frontend.py` | 自适应增益 + 噪声底门限（修“开头几秒被当噪声”） |
| `see_now.py` / `ocr.py` | 看屏（ffmpeg 抓帧→图片）与系统 OCR（`screen.text`，0 图片 token）；11/04 上线 |
| `embodied/companion/{constitution,memory_stabilization}` | 仅存的 embodied 模块（其余已归档） |

工具注册与执行只有一条路：`target_capability_registry.py`（`CapabilityRegistry`，
策略 fail-closed）+ `target_scheduler_tools.py`（能力定义），LLM 工具面由
`CapabilityRegistry.export_openai_tools()` 导出。
Agent-Core（`backend/agent/` 的 brain/planner/tool_executor/ToolRegistry）已于 2026-09-24 整体归档，
不再有第二套注册表。

**能力面（2026-11-05）**：`YHLZ_SEE_NOW=1` 时 **47 个工具**，含 `see_now`（看图）与 `screen_text`（系统 OCR）。
`/state` 的 `ollama` 可选：未启用时报 `off`、不做探活（避免每次轮询白等 ~2 s）。

## tools/（按用途）

- 启动 / 看护：`yhlz_launcher.py`、`yhlz_watchdog.py`、`daemon_restart.py`
- 体检 / 门禁：`smoke.py`、`ci_check.py`、`env_guard.py`、`snapshot.py`、`memory_drain.py`
- QQ：**Lite 独占**（`config/qq_management.json`=external）——`qq_bridge_service.py`（桥服务）、
  `qq_bridge_watchdog.py`（Lite 看护）、`qq_bridge_control.py`（整链启停）；旧 Full 链
  `napcat_watch.py` 在 external 模式下由启动器/看门狗收掉；`qq_bot_restart.py` 只转调 Lite control。
  **`qq_bot.py` 不是死代码**（2215 行，共享库 + Full 链运行代码的混合体，被 17 个非测试模块 import）；
  删它之前先看架构债 C1 的三步剥离计划。
- MCP：`yhlz_mcp_server.py`（台账 / 记忆 / 文件 / 网络 / 时间）、`lizhen_cmd_mcp.py`（cmd / cmd_station）
- 台账：`ledger_cli.py`（增删查改 + `check`）、`ledger_mem_import.py`（索引）
- 语音底层：`tts_test_start.py`；派单：`dev_runner.py`；翻唱：`cover_*.py` / `gsv5_*.py`；看屏：见 backend
- 评测与训练：`persona_regression.py`、`memory_eval.py`、`v9_*.py`、`finetune_*.py`、`llm_workbench/`

## 评测与训练数据（都不占 GPU 的那部分）

| 目的 | 命令 |
|---|---|
| 人格 / 关系 / 工具遵循回归（版本×得分表） | `python tools/persona_regression.py --live --version v7b`（需 8081/LLM）；离线评分 `--answers <文件>` |
| 记忆评测（LoCoMo + 自建场景） | `python tools/memory_eval.py scenes\|locomo` |
| 台账知识问答 | `python tools/ledger_qa_run.py` |
| 真实语料标注（"这条我要"） | `python tools/golden_build.py review` → `pick 1 3 7` → `coverage` 看占比 |
| 训练集装配（版本化） | `python tools/finetune_assemble.py --tag vX` |
| 记忆向量补齐 / 一致性巡检 | `python tools/vec_backfill.py --check`（只读）\| 无参补齐 \| `--prune` |

**真实语料唯一来源**：`cache/sessions/*.json`（老爹↔元亨的存档会话）→
`tools/finetune_build.py` → `data/finetune/sft_persona.jsonl` → 装配时计为 `real`。
QQ 群导出只做知识 corpus（纪律：别人的话不得伪装成元亨对话）。

## 前端

- `assets/webui/`：工作台（由 8321 服务）：`index.html` / `console.css` / `console.js`
- `desktop/`：Electron 桌宠（依赖未入库的 `desktop/node_modules`）
- `assets/vendor/live2d/`：Live2D 运行库

## 配置与依赖

- `config/qqwatch.json`（入库，token 留空）+ `config/qqwatch.local.json`（**未入库**，真实 token）
- `.env`（**未入库**，密钥）；`opencode.json` 已退役并于 2026-10-21 移入 `archive/2026-10-21-retired/`（原台账 0497）
- **环境（2026-11-05 收敛后 3 套）**：`.venv`（运行时）、`venv-dsh`（利贞 harness SDK）、`venv-gsv5`（翻唱链）。
  `venv-train` / `venv-sep` 已确认无引用并删除。
- `requirements-target-{llm,asr,input}.txt`、`requirements-tts-primary.txt`、`requirements-target-runtime.txt`
- `.venv/Lib/site-packages/sitecustomize.py`：解释器启动即清 `NO_PROXY` 的 `[::1]`（httpx `InvalidURL` 根因）；
  参照实现 `tools/env_guard.py`。backend 导入时也会消毒一次。

## 运行产物（未入库）

- `cache/`（记忆库 / 快照 / 日志 / 临时）、`data/`、`models/`

## 归档

- `archive/2026-09-12-prune/`：P2 归档的旧世代代码（`embodied` 大部分、`vision` / `personality` / `action` / `voice_identity` / `main.py`、`plugins` / `frontend` / `updates` / `apps` / `webui_templates` / `webui_server.py` / `start.bat` 等）。
- `archive/2026-09-24-deadcode/`：live 链零引用的旧链路——
  `context_manager.py` / `conversation_manager.py`、`agent/`（Agent-Core 整包 + 10 个测试）。
- `archive/2026-10-21-retired/`：`opencode.json`（opencode 时代 MCP 注册）。
- `archive/2026-11-05-root-clutter/`：仓库根旧散件（18 个 html/json/怪名文件 + 20 个实验 wav，197.9 MB），
  仅本地留档、`.gitignore` 排除。

## 历史遗留（不在三区内，保留但已与当前链路脱钩）

- `对话DEMO/`：M0 语音身份时期的独立 demo + 测试；依赖已归档的 `context_manager` / `backend.main`。
  **不再是测试基线的一部分**，当前测试基线是 `backend/test_*.py`（`python -m unittest backend.test_xxx`）。

## 外部（不在仓库）

- 模型：`C:\Users\ACE_WAN——PROJECT\models\gemma4\`、`models/voice/...`（`YH_MODELS_DIR` 可配）
- QQ：`C:\Users\ACE_WAN——PROJECT\qqwatch\shell\`（NapCat）

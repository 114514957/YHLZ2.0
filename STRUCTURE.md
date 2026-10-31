# YH 项目结构

> 更新：2026-10-21（入口改名 YH、退役文件归档、结构偏差登记，台账 0957）。上一版 2026-09-24（死代码归档，台账 0496）；再上一版 2026-09-12（台账 0295）。
>
> 结构债清单与改进计划见 `docs/架构债清单与改进计划_20261021.md`；本文与它冲突时，以架构债清单里的实测证据为准。

## 定位

本机数字生命体：本地 Gemma 主脑 + 记忆 / 成长 / 学习 / 思考 + 工作台 / 桌宠 / QQ / 语音。面向 RTX 4060 Laptop 8GB。

## 三区划分（判断一个模块属于哪区，先看这里）

| 区 | 判据 | 位置 |
|---|---|---|
| **live** | 被 `YH_boot.bat` → `tools/yhlz_launcher.py` / `tools/yhlz_watchdog.py` / `tools/qq_bridge_service.py`、`backend/target_daemon.py`（8321）、`tools/qq_bot.py`、`tools/yhlz_mcp_server.py` 的 import 图可达 | `backend/`（除下表所列）、`tools/`、`assets/`、`desktop/` |
| **测试专用（test-only）** | 只被 `backend/test_*.py` 或 `tools/*eval*.py` 引用，live 链不可达 | 例：`tools/memory_eval.py`、`tools/ab_chat.py`、`tools/llm_compare.py`、`tools/style_ab.py` |
| **归档（archive）** | live 与最小编译检查都不需要 | `archive/` |

新增/删改模块时按此三区自检；落进 archive 的模块不再维护，只在考古时读。

## 入口

| 入口 | 说明 |
|---|---|
| `YH_boot.bat` | **唯一开机自启**（Windows 启动项 `YH 开机自启.lnk`）：服务栈 → Full 看门狗 → QQ Lite `resume` |
| `YH_workbench_normal.bat` | 手动启动工作台（普通权限守卫，拒绝管理员令牌） |
| `YH_全家桶.bat` | 兼容入口：转调 `YH_boot.bat` + 开工作台 + 桌宠 |
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
| `embodied/companion/{constitution,memory_stabilization}` | 仅存的 embodied 模块（其余已归档） |

工具注册与执行只有一条路：`target_capability_registry.py`（`CapabilityRegistry`，
策略 fail-closed）+ `target_scheduler_tools.py`（能力定义），LLM 工具面由
`CapabilityRegistry.export_openai_tools()` 导出。Agent-Core（`backend/agent/` 的
brain/planner/tool_executor/ToolRegistry）已于 2026-09-24 整体归档，不再有第二套注册表。

## tools/

- 启动 / 看护：`yhlz_launcher.py`、`yhlz_watchdog.py`、`daemon_restart.py`
- 体检：`smoke.py`（只读，一条命令报栈状态；`--json` 机读；FAIL 才算挂，WARN 表示降级）
- QQ：**Lite 独占**（`config/qq_management.json`=external）——`qq_bridge_service.py`（桥服务）、
  `qq_bridge_watchdog.py`（Lite 看护）、`qq_bridge_control.py`（整链启停）；旧 Full 链
  `napcat_watch.py` 在 external 模式下由启动器/看门狗收掉；
  `qq_bot_restart.py` 只转调 Lite control，`qq_bot_start.bat` 已删除
- **`qq_bot.py` 不是死代码（2026-10-21 更正）**：2215 行，是「共享库 + Full 链运行代码」的混合体，
  被 17 个非测试模块 import（含 `console_server.py`、`qq_bridge_service.py`、`qq_bridge_watchdog.py`、
  `yhlz_launcher.py`、`yhlz_watchdog.py`）。退役的是 Full 链的**运行方式**，不是这个模块。
  删它之前先看架构债 C1 的三步剥离计划。
- MCP：`yhlz_mcp_server.py`（台账 / 记忆 / 文件 / 网络 / 时间）
- 语音底层：`tts_test_start.py`；派单：`dev_runner.py`；快照：`snapshot.py`

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
- 利贞 harness：`venv-dsh/`（SDK 独立 venv，未入库）+ `tools/dsh_worker.py`（常驻网关：`/start`/`/answer` 与 job 面）+ `tools/dev_contract.py`（提示词/分类契约）+ `tools/harness_gateway.py`（网关客户端）；MCP 覆盖层生成在 `cache/dev/harness_mcp.patch.yml`
- `requirements-target-{llm,asr,input}.txt`、`requirements-tts-primary.txt`、`requirements-target-runtime.txt`

## 运行产物（未入库）

- `cache/`（记忆库 / 快照 / 日志 / 临时）、`data/`

## 归档

- `archive/2026-09-12-prune/`：P2 归档的旧世代代码（`embodied` 大部分、`vision` / `personality` / `action` / `voice_identity` / `main.py`、`plugins` / `frontend` / `updates` / `apps` / `webui_templates` / `webui_server.py` / `start.bat` 等）。
- `archive/2026-09-24-deadcode/`：live 链零引用的旧链路——
  - `context_manager.py` / `conversation_manager.py`（旧回合/上下文栈，最后触点 `archive/2026-09-12-prune/backend_main.py`）；
  - `agent/`（Agent-Core 整包：brain / planner / tool_executor / llm_adapter / memory / ToolRegistry + 其 10 个测试；唯一 live 触点曾是 `target_scheduler_tools.setup_scheduler_tools` 桥，已随包删除）。
- `archive/2026-10-21-retired/`：`opencode.json`（opencode 时代 MCP 注册，2026-10-21 移入）。旧的 `.opencode-backup-20261008-101357`（0.2 GB）已移出仓库到 `C:\Users\ACE_WAN——PROJECT\_backup\`，不再占仓库空间。

## 历史遗留（不在三区内，保留但已与当前链路脱钩）

- `对话DEMO/`：M0 语音身份时期的独立 demo + 测试；其中 `test_voice_identity_compat.py` /
  `test_v1_final_audit.py` 依赖已归档的 `context_manager`，`test_m04_endpoints_smoke.py` /
  `test_comprehensive.py` 依赖已归档的 `backend.main`。**不再是测试基线的一部分**，
  当前测试基线是 `backend/test_*.py`（`python -m unittest backend.test_xxx`）。

## 外部（不在仓库）

- 模型：`C:\Users\ACE_WAN——PROJECT\models\gemma4\`、`models/voice/...`（`YH_MODELS_DIR` 可配）
- QQ：`C:\Users\ACE_WAN——PROJECT\qqwatch\shell\`（NapCat）

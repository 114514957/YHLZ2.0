# YHLZ 项目结构

> 更新：2026-09-12（P3 文档刷新，台账 0295）。旧版（2026-08-03）已过时。

## 定位

本机数字生命体：本地 Gemma 主脑 + 记忆 / 成长 / 学习 / 思考 + 工作台 / 桌宠 / QQ / 语音。面向 RTX 4060 Laptop 8GB。

## 入口

| 入口 | 说明 |
|---|---|
| `YHLZ_全家桶.bat` → `tools/yhlz_launcher.py` | 一键拉起 Gemma / ollama / daemon / QQ 桥 / 看护 / 桌宠 |
| `backend/target_daemon.py` | 常驻 daemon，端口 **8321**（工作台 UI + API） |
| `backend/console_server.py` | 工作台 HTTP 处理器（`ConsoleHandler`） |

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

## tools/

- 启动 / 看护：`yhlz_launcher.py`、`yhlz_watchdog.py`、`daemon_restart.py`
- QQ：`qq_bot.py`（桥）、`napcat_watch.py`（掉线看护）、`qq_bot_restart.py`
- MCP：`yhlz_mcp_server.py`（台账 / 记忆 / 文件 / 网络 / 时间）
- 语音底层：`tts_test_start.py`；派单：`dev_runner.py`；快照：`snapshot.py`

## 前端

- `assets/webui/`：工作台（由 8321 服务）：`index.html` / `console.css` / `console.js`
- `desktop/`：Electron 桌宠（依赖未入库的 `desktop/node_modules`）
- `assets/vendor/live2d/`：Live2D 运行库

## 配置与依赖

- `config/qqwatch.json`（入库，token 留空）+ `config/qqwatch.local.json`（**未入库**，真实 token）
- `.env`（**未入库**，密钥）；`opencode.json`（MCP server 注册）
- `requirements-target-{llm,asr,input}.txt`、`requirements-tts-primary.txt`、`requirements-target-runtime.txt`

## 运行产物（未入库）

- `cache/`（记忆库 / 快照 / 日志 / 临时）、`data/`

## 归档

- `archive/2026-09-12-prune/`：P2 归档的旧世代代码（`embodied` 大部分、`vision` / `personality` / `action` / `voice_identity` / `main.py`、`plugins` / `frontend` / `updates` / `apps` / `webui_templates` / `webui_server.py` / `start.bat` 等）。

## 外部（不在仓库）

- 模型：`C:\Users\ACE_WAN——PROJECT\models\gemma4\`、`models/voice/...`（`YHLZ_MODELS_DIR` 可配）
- QQ：`C:\Users\ACE_WAN——PROJECT\qqwatch\shell\`（NapCat）

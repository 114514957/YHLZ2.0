# YHLZ 元亨 · 数字生命

本机（RTX 4060 Laptop 8GB）上的数字生命体：**本地 Gemma 主脑** + 五支柱（情感 / 记忆 / 成长 / 学习 / 思考）+ 工作台 / 桌面桌宠 / QQ / 语音。

> 数字生命（非扮演）；关系不变量：与老爹的关系永存、老爹主导性不可变。

## 快速开始

双击 **`YHLZ_全家桶.bat`**（→ `tools/yhlz_launcher.py`）会拉起：

- 本地 Gemma（llama.cpp，端口 **8081**）
- Ollama 离线兜底（**11434**）
- 常驻 daemon（工作台 UI + API，端口 **8321**）
- QQ 桥（`tools/qq_bot.py`）、NapCat 掉线看护、桌面桌宠（Electron）

然后浏览器打开 <http://127.0.0.1:8321>。

## 两条 LLM 链路

| 链路 | 模型 | 说明 |
|---|---|---|
| 元亨本体（对话 / 人格） | 本地 **Gemma-4-E4B-Aggressive**（`gemma4-e4b-aggr-q4km.gguf` + 视觉 `mmproj`） | llama.cpp 起，端口 8081，reasoning 模型 |
| 开发派单（`[[dev:]]`） | **deepseek/deepseek-v4-flash** | opencode headless，agent `yhlz-dev`（禁 git commit/push） |

## 感知链路（本地优先）

- **ASR**：SenseVoiceSmall（FunASR）+ sherpa-onnx 流式（边说边出）
- **TTS**：Qwen3-TTS（faster-qwen3-tts，主）+ edge-tts（兜底）
- **VAD / 门限**：`backend/voice_frontend.py`
- 语音**只在工作台 / 桌宠**做连续对话；QQ 语音为“语音消息”

## 工作台入口

- UI：<http://127.0.0.1:8321>（`assets/webui/`）
- 文本对话：`POST /v1/chat/completions`（stream）或 `POST /turn`
- 语音：`POST /voice`
- 面板：`/state /logs /growth /ledger /mem /sessions /drives /monitor`

## 记忆

- L1 / L2 / L3；主库 `cache/memstore/memstore.db`，向量侧表 `cache/embvec.db`
- **零删除**（只降权 / 归档）；快照 `cache/snapshots/`
- 成长日志：`docs/元亨的成长日志.md`

## 开发 / Agent

- opencode 通过 `opencode.json` 的 `yhlz` MCP 工具查询台账 / 记忆（`tools/yhlz_mcp_server.py`）
- 台账（**唯一事实源**）：`docs/上下文台账.md`
- 台账增删查改（任何 agent 通用程序）：`python tools/ledger_cli.py {search,list,get,add,update,delete,stats,index}`
  （Python 直接 `import backend.ledger_store`；MCP 工具 `ledger_search/get/list/add/update/delete` 同源）
- 规则：`AGENTS.md`

## 说明

- Python 3.12 + `.venv`；目录结构见 `STRUCTURE.md`。
- 依赖：按用途看 `requirements-target-*.txt` / `requirements-tts-primary.txt` / `requirements-target-runtime.txt`；根 `requirements.txt` 为**旧版聚合，已过时**。
- 旧世代代码（embodied / vision / personality / action / voice_identity / main.py 等）已归档到 `archive/2026-09-12-prune/`。

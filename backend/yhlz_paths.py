"""Central external-path / account-id config (ledger 0296).

总目录 `YHLZ` 下分 `YH`（本仓库）和 `LZ`；外部项目（`qqwatch`, `models`,
`NEKO`）在 `EXTERNAL` = 本仓库的祖父目录（即 `...\\PROJECT`）。Override:

    YH_EXTERNAL_DIR     base dir containing qqwatch/ models/ (default: PROJECT)
    YH_MODELS_DIR       models dir (default: EXTERNAL/models)
    YH_QQ_BOT_UIN       Yuanheng QQ account  (default 3655185302)
    YH_QQ_MASTER_UIN    owner QQ account     (default 2258374446)
    YH_OLLAMA_EXE       ollama.exe path
    YH_LLAMA_EXE        llama-server.exe path
    YH_DESKTOP_DIR      Desktop 图片素材 dir

Legacy `YHLZ_*` names are still accepted as fallbacks. No module here reads
the network or starts anything — pure config.
"""
from __future__ import annotations

import os
import pathlib


def _env(name: str, legacy: str, default: str) -> str:
    return os.getenv(name) or os.getenv(legacy) or default


ROOT = pathlib.Path(__file__).resolve().parent.parent
EXTERNAL = pathlib.Path(_env(
    "YH_EXTERNAL_DIR", "YHLZ_EXTERNAL_DIR", str(ROOT.parent.parent)))

QQWATCH = EXTERNAL / "qqwatch"
QQWATCH_SHELL = QQWATCH / "shell"
QQWATCH_CONFIG = QQWATCH_SHELL / "config"
NAPCAT_LAUNCHER = QQWATCH_SHELL / "launcher-user.bat"
NAPCAT_START_BAT = QQWATCH / "start-napcat.bat"
NAPCAT_QR = QQWATCH_SHELL / "cache" / "qrcode.png"
NAPCAT_WEBUI = QQWATCH_SHELL / "config" / "webui.json"

MODELS_DIR = pathlib.Path(_env(
    "YH_MODELS_DIR", "YHLZ_MODELS_DIR", str(EXTERNAL / "models")))
GEMMA_GGUF = MODELS_DIR / "gemma4" / "gemma4-e4b-aggr-q3km.gguf"
MMPROJ_GGUF = MODELS_DIR / "gemma4" / "mmproj-gemma4-e4b.gguf"

# v6 生产链（记录 0398/0426）：项目内模型目录（QAT-Q4 + mmproj + yuanheng-v6 LoRA）
LOCAL_MODELS = ROOT / "models"
YH_LLAMA_EXE = LOCAL_MODELS / "llama-cuda" / "llama-server.exe"
YH_BASE_GGUF = LOCAL_MODELS / "gemma4-gguf" / "gemma-4-E4B_q4_0-it.gguf"
YH_MMPROJ_GGUF = LOCAL_MODELS / "gemma4-gguf" / "gemma-4-E4B-it-mmproj.gguf"
# 生产 LoRA（记录 0432）：v7b = v6-dpo + 语音(真实域ASR+应答+rehearsal)
# 历史：v6(0398) -> v7b；回滚可指回 yuanheng-v6-lora.gguf
YH_LORA_GGUF = LOCAL_MODELS / "gguf-lora" / "yuanheng-v7b-lora.gguf"

BOT_UIN = str(_env("YH_QQ_BOT_UIN", "YHLZ_QQ_BOT_UIN", "3655185302"))
MASTER_UIN = str(_env("YH_QQ_MASTER_UIN", "YHLZ_QQ_MASTER_UIN", "2258374446"))

OLLAMA_EXE = _env(
    "YH_OLLAMA_EXE", "YHLZ_OLLAMA_EXE",
    str(EXTERNAL / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"))
LLAMA_EXE = _env(
    "YH_LLAMA_EXE", "YHLZ_LLAMA_EXE",
    str(EXTERNAL / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        / "ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "llama-server.exe"))
DESKTOP_DIR = pathlib.Path(_env(
    "YH_DESKTOP_DIR", "YHLZ_DESKTOP_DIR",
    str(EXTERNAL / "Desktop" / "图片素材")))

# repo-local helpers
QQWATCH_RUN_BAT = ROOT / "qqwatch-run.bat"
QQWATCH_EXTRACT_BAT = ROOT / "qqwatch-extract.bat"

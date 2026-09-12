"""Central external-path / account-id config (ledger 0296).

The repo lives at `<EXTERNAL>/YHLZ`; sibling projects (`qqwatch`, `models`,
`NEKO`) sit under `EXTERNAL` = repo parent. Override for portability:

    YHLZ_EXTERNAL_DIR   base dir containing qqwatch/ models/ (default: repo parent)
    YHLZ_MODELS_DIR     models dir (default: EXTERNAL/models)
    YHLZ_QQ_BOT_UIN     Yuanheng QQ account  (default 3655185302)
    YHLZ_QQ_MASTER_UIN  owner QQ account     (default 2258374446)
    YHLZ_OLLAMA_EXE     ollama.exe path
    YHLZ_LLAMA_EXE      llama-server.exe path
    YHLZ_DESKTOP_DIR    Desktop 图片素材 dir

No module here reads the network or starts anything — pure config.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXTERNAL = pathlib.Path(os.getenv("YHLZ_EXTERNAL_DIR", str(ROOT.parent)))

QQWATCH = EXTERNAL / "qqwatch"
QQWATCH_SHELL = QQWATCH / "shell"
QQWATCH_CONFIG = QQWATCH_SHELL / "config"
NAPCAT_LAUNCHER = QQWATCH_SHELL / "launcher-user.bat"
NAPCAT_START_BAT = QQWATCH / "start-napcat.bat"
NAPCAT_QR = QQWATCH_SHELL / "cache" / "qrcode.png"

MODELS_DIR = pathlib.Path(os.getenv("YHLZ_MODELS_DIR", str(EXTERNAL / "models")))
GEMMA_GGUF = MODELS_DIR / "gemma4" / "gemma4-e4b-aggr-q4km.gguf"
MMPROJ_GGUF = MODELS_DIR / "gemma4" / "mmproj-gemma4-e4b.gguf"

BOT_UIN = str(os.getenv("YHLZ_QQ_BOT_UIN", "3655185302"))
MASTER_UIN = str(os.getenv("YHLZ_QQ_MASTER_UIN", "2258374446"))

OLLAMA_EXE = os.getenv(
    "YHLZ_OLLAMA_EXE",
    str(EXTERNAL / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"))
LLAMA_EXE = os.getenv(
    "YHLZ_LLAMA_EXE",
    str(EXTERNAL / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        / "ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "llama-server.exe"))
DESKTOP_DIR = pathlib.Path(
    os.getenv("YHLZ_DESKTOP_DIR", str(EXTERNAL / "Desktop" / "图片素材")))

# repo-local helpers
QQWATCH_RUN_BAT = ROOT / "qqwatch-run.bat"
QQWATCH_EXTRACT_BAT = ROOT / "qqwatch-extract.bat"

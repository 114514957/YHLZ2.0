"""本地 LLM 封存开关（2026-11-18，老爹定：维持云端、本地封存）。

`YHLZ_LOCAL_LLM_SEALED=1` 或存在 `config/local_llm_sealed.flag` 时：
- launcher / watchdog / gpu_window 不再拉起 8081 的 llama-server；
- 聊天继续走 config/llm.local.json 的云端端点；
- 记忆抽取（kg_v2）改用云端（有 key 时），否则跳过；
- 本地模型文件不删除，随时可解封回滚。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAG = ROOT / "config" / "local_llm_sealed.flag"


def sealed() -> bool:
    v = str(os.getenv("YHLZ_LOCAL_LLM_SEALED", "")).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return FLAG.exists()


def unseal_hint() -> str:
    return ("本地 LLM 已封存：删 config/local_llm_sealed.flag 并重启栈即可恢复 8081；"
            "聊天当前走云端，不受影响。")

"""adapter → GGUF 转换（后台任务）。

工具链（台账 1063 验证过的那套）：
    models/llama-cuda/src/llama.cpp-b10991/convert_lora_to_gguf.py
      --outfile <models/gguf-lora/xxx-lora.gguf> --outtype f16
      --base models/gemma4-hf/gemma-4-e4b-it <adapter 目录>

两个坑记在这：
  · 必须用 `src/llama.cpp-b10991/` 那份脚本；`models/llama-cuda/tools/` 那份缺 conversion 包。
  · cwd 用 YH 根就行——脚本目录会自动进 sys.path，`conversion` 照样能 import。
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # YH/
CONVERT_SCRIPT = os.path.join(ROOT, "models", "llama-cuda", "src",
                              "llama.cpp-b10991", "convert_lora_to_gguf.py")
HF_BASE = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")
OUT_DIR = os.path.join(ROOT, "models", "gguf-lora")
LOG_DIR = os.path.join(HERE, "data", "logs")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

_LOCK = threading.Lock()
_JOB: dict = {"running": False, "error": "", "version": "", "out": "", "log": "",
              "started_at": 0, "finished_at": 0, "ok": None}


def state() -> dict:
    with _LOCK:
        d = dict(_JOB)
    p = d.get("log") or ""
    d["log_tail"] = _tail(p, 8000) if p else ""
    return d


def _tail(path: str, n: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def default_out_name(version: str) -> str:
    """yuanheng-v9t6-lora.gguf 这种命名，和现有 9 个保持一致。"""
    v = re.sub(r"[^A-Za-z0-9._-]", "-", version).strip("-")
    return "yuanheng-%s-lora.gguf" % v


def start(adapter_path: str, version: str, out_name: str = "") -> dict:
    with _LOCK:
        if _JOB.get("running"):
            return {"ok": False, "error": "已经有一个转换在跑"}
        if not os.path.isfile(CONVERT_SCRIPT):
            return {"ok": False, "error": "缺转换脚本：%s" % CONVERT_SCRIPT}
        if not os.path.isdir(adapter_path):
            return {"ok": False, "error": "adapter 目录不存在：%s" % adapter_path}
        if not os.path.isdir(HF_BASE):
            return {"ok": False, "error": "缺 HF 基座：%s" % HF_BASE}
        out_name = out_name or default_out_name(version)
        if not out_name.endswith(".gguf"):
            out_name += ".gguf"
        out_path = os.path.join(OUT_DIR, os.path.basename(out_name))
        if os.path.exists(out_path):
            return {"ok": False, "error": "目标已存在，先改名或删掉：%s" % out_path}
        os.makedirs(LOG_DIR, exist_ok=True)
        log = os.path.join(LOG_DIR, "convert_%s_%d.log" % (version, int(time.time())))
        _JOB.update({"running": True, "error": "", "version": version,
                     "out": out_path, "log": log, "started_at": time.time(),
                     "finished_at": 0, "ok": None})

    cmd = [PY, CONVERT_SCRIPT, "--outfile", out_path, "--outtype", "f16",
           "--base", HF_BASE, adapter_path]

    def worker() -> None:
        ok = False
        err = ""
        try:
            with io.open(log, "w", encoding="utf-8", errors="replace") as f:
                f.write("$ " + " ".join(cmd) + "\n\n")
                f.flush()
                r = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                   timeout=1800)
            if r.returncode != 0:
                err = "转换脚本退出码 %d（看日志）" % r.returncode
            elif not os.path.exists(out_path):
                err = "脚本跑完了但没生成文件"
            else:
                size = os.path.getsize(out_path)
                if size < 1024:
                    err = "产出的文件只有 %d 字节" % size
                else:
                    ok = True
        except subprocess.TimeoutExpired:
            err = "超过 30 分钟没跑完"
        except Exception as ex:  # noqa: BLE001
            err = "%s: %s" % (type(ex).__name__, ex)
        with _LOCK:
            _JOB.update({"running": False, "ok": ok, "error": err,
                         "finished_at": time.time()})

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "out": out_path, "log": log}


if __name__ == "__main__":
    print(json.dumps({"script": CONVERT_SCRIPT, "exists": os.path.isfile(CONVERT_SCRIPT),
                      "hf_base": HF_BASE, "base_exists": os.path.isdir(HF_BASE),
                      "out_dir": OUT_DIR, "py": PY}, ensure_ascii=False, indent=1))

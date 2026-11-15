# -*- coding: utf-8 -*-
"""在 llama.cpp 源码树里转换 v13 adapter → GGUF（cwd 必须是树根，才能 import conversion）。"""
from __future__ import annotations

import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TREE = os.path.join(ROOT, "models", "llama-cuda", "src", "llama.cpp-b10991")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
CONV = os.path.join(TREE, "convert_lora_to_gguf.py")
ADAPTER = os.path.join(ROOT, "models", "lora", "yuanheng-v13")
BASE_HF = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")
OUT = os.path.join(ROOT, "models", "gguf-lora", "yuanheng-v13-lora.gguf")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
cmd = [PY, CONV, ADAPTER, "--base", BASE_HF, "--outfile", OUT, "--outtype", "f16"]
print("cwd = %s" % TREE)
print("cmd = %s\n" % " ".join(os.path.basename(c) if i == 1 else c
                              for i, c in enumerate(cmd)))
r = subprocess.run(cmd, cwd=TREE, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print(r.stdout[-2500:] or "(无标准输出)")
if r.returncode != 0:
    print("[stderr]\n" + (r.stderr or "")[-2500:])
    sys.exit(1)
print("\n产出：%s（%.1f MB）" % (os.path.basename(OUT), os.path.getsize(OUT) / 1048576))

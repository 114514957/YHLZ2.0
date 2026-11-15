# -*- coding: utf-8 -*-
"""把 v9t10-dpo 的 adapter 校验并转成 GGUF。"""
from __future__ import annotations

import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import registry  # noqa: E402

import sys as _s
TAG = _s.argv[1] if len(_s.argv) > 1 else "v9t10-dpo"
LORA_DIR = os.path.join(YH, "models", "lora", "yuanheng-" + TAG)
ADAPTER = os.path.join(LORA_DIR, "adapter_model.safetensors")
CONVERT = os.path.join(YH, "models", "llama-cuda", "src", "llama.cpp-b10991",
                       "convert_lora_to_gguf.py")
HF_BASE = os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it")
OUT = os.path.join(YH, "models", "gguf-lora", "yuanheng-%s-lora.gguf" % TAG)

print("== 1. adapter 完整性 ==")
info = registry.inspect_safetensors(ADAPTER)
print("   文件 %d 字节 | 张量 %d | 头 %d | 期望 %d | %s"
      % (info["actual"], info["tensors"], info["header_len"], info["expect"],
         "✅ 自洽" if info["ok"] else "❌ " + str(info.get("err"))))
if not info["ok"]:
    sys.exit("✗ adapter 不完整")

print("\n== 2. 转 GGUF ==")
cmd = [sys.executable, CONVERT, "--outfile", OUT, "--outtype", "f16",
       "--base", HF_BASE, LORA_DIR]
t0 = __import__("time").time()
r = subprocess.run(cmd, cwd=YH, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("   退出码 %s | %.0f 秒" % (r.returncode, __import__("time").time() - t0))
if r.returncode != 0:
    print(r.stdout[-1200:])
    print(r.stderr[-1200:])
    sys.exit("✗ 转换失败")

print("\n== 3. 产物 ==")
if os.path.exists(OUT):
    import hashlib
    h = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print("   %s\n   %d 字节（%.2f MB）\n   sha256 %s…"
          % (OUT, os.path.getsize(OUT), os.path.getsize(OUT) / 1048576, h[:16]))
else:
    sys.exit("✗ 没生成 GGUF")

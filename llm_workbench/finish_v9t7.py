# -*- coding: utf-8 -*-
"""训练后收尾：校验 adapter → 转 GGUF → 报数字。

不做评测（评测交给工作台），只保证"下载的东西是完整的、转出来的 GGUF 可用"。
台账 1061 的教训：只看 safetensors 头会误判残缺，必须算
    8 + header_len + max(offset+len) == 文件大小
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))

import registry  # noqa: E402

LORA_DIR = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t7")
ADAPTER = os.path.join(LORA_DIR, "adapter_model.safetensors")
CONVERT = os.path.join(YH, "models", "llama-cuda", "src", "llama.cpp-b10991",
                       "convert_lora_to_gguf.py")
HF_BASE = os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it")
PY = sys.executable

print("== 1. adapter 完整性 ==")
if not os.path.exists(ADAPTER):
    sys.exit("✗ 没有 adapter：%s（先 --fetch）" % ADAPTER)
info = registry.inspect_safetensors(ADAPTER)
print("   文件 %d 字节 | 张量 %d | 头 %d | 期望 %d | %s"
      % (info["actual"], info["tensors"], info["header_len"], info["expect"],
         "✅ 自洽" if info["ok"] else "❌ " + info["err"]))
if not info["ok"]:
    sys.exit("✗ adapter 不完整，别往下走")

print("\n== 2. 转 GGUF ==")
out = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t7-lora.gguf")
if os.path.exists(out):
    print("   已存在，跳过：%s" % out)
else:
    cmd = [PY, CONVERT, "--outfile", out, "--outtype", "f16",
           "--base", HF_BASE, LORA_DIR]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=YH, capture_output=True, text=True)
    print("   退出码 %s | %.0fs" % (r.returncode, time.time() - t0))
    if r.returncode != 0:
        print((r.stdout or "")[-1200:])
        print((r.stderr or "")[-1200:])
        sys.exit("✗ 转换失败")

print("\n== 3. 产出 ==")
sz = os.path.getsize(out)
print("   %s" % out)
print("   %d 字节（%.2f MB）" % (sz, sz / 1048576))
print("   sha256 前16: %s" % registry._sha256(out)[:16])
print("\n下一步：工作台起服务（-ngl 0 走 CPU 也行）→ 跑 56 题 + 26 题群聊")

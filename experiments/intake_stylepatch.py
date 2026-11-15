# -*- coding: utf-8 -*-
"""落地 stylepatch4：解包 → 校验 → 转 GGUF。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DEST = os.path.join(YH, "models", "lora", "yuanheng-stylepatch4")
SHA = "58a0cc770bdb478c8ea4dfcd0a8a729841924d4963312d6e822017945b076b46"

src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    YH, "docs", "训练产物", "pack_stylepatch4.tar.gz")
size = os.path.getsize(src)
h = hashlib.sha256()
with open(src, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print("[1] %s｜%d 字节" % (os.path.basename(src), size))
print("    sha256 %s｜一致 %s" % (h.hexdigest()[:16], h.hexdigest() == SHA))

print("\n[2] 解包 → %s" % DEST)
os.makedirs(DEST, exist_ok=True)
with tarfile.open(src, "r:gz") as tf:
    tf.extractall(DEST)
adp = os.path.join(DEST, "adapter_model.safetensors")
for root, _d, files in os.walk(DEST):
    if "adapter_model.safetensors" in files:
        adp = os.path.join(root, "adapter_model.safetensors")
        break
print("    adapter %d 字节" % os.path.getsize(adp))

print("\n[3] 转 GGUF")
t0 = time.time()
r = subprocess.run([sys.executable,
                    os.path.join(YH, "experiments", "finish_dpo.py"),
                    "stylepatch4"],
                   cwd=YH, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print(r.stdout[-1200:])
if r.returncode != 0:
    print(r.stderr[-600:])
    sys.exit("转换失败")
print("用时 %.0f 秒" % (time.time() - t0))

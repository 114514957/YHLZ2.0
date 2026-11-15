# -*- coding: utf-8 -*-
"""老爹从面板拉下来的包，落地成可用 adapter：解包 → 校验 → 转 GGUF。

用法：
  python intake_v11.py "C:\\Users\\...\\pack_v11.tar.gz"
  python intake_v11.py            # 不给参数就用 cache 里那份后台下的
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DEST = os.path.join(YH, "models", "lora", "yuanheng-v11")
SHA = "a7f1f01d982aaca79580de805fa79009c90e1268a4f40fdc586270e6726642df"
WANT = 134726178

src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(YH, "cache", "pack_v11.tar.gz")
if not os.path.exists(src):
    sys.exit("没找到包：%s" % src)

size = os.path.getsize(src)
print("[1] 包：%s｜%d 字节" % (os.path.basename(src), size))
h = hashlib.sha256()
with open(src, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
digest = h.hexdigest()
print("    sha256 %s" % digest)
if size != WANT or digest != SHA:
    print("    ⚠️ 大小或 sha 对不上（期望 %d / %s）" % (WANT, SHA[:16]))
    print("    可能是面板重新打包过，继续试解压；解不开就说明包坏了。")

print("\n[2] 解包到 %s" % DEST)
os.makedirs(DEST, exist_ok=True)
with tarfile.open(src, "r:gz") as tf:
    names = tf.getnames()
    print("    条目 %d 个，前 6 条：%s" % (len(names), names[:6]))
    tf.extractall(DEST)

have = os.path.join(DEST, "adapter_model.safetensors")
if not os.path.exists(have):
    # 包里可能带一层目录
    for root, _d, files in os.walk(DEST):
        if "adapter_model.safetensors" in files:
            have = os.path.join(root, "adapter_model.safetensors")
            break
if not os.path.exists(have):
    sys.exit("✗ 解出来没有 adapter_model.safetensors")

print("    adapter %d 字节｜%.1f MB" % (os.path.getsize(have),
                                      os.path.getsize(have) / 1048576))

print("\n[3] 校验 + 转 GGUF（复用 finish_dpo.py）")
t0 = time.time()
r = subprocess.run([sys.executable, os.path.join(YH, "experiments", "finish_dpo.py"), "v11"],
                   cwd=YH, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print(r.stdout[-1500:])
if r.returncode != 0:
    print(r.stderr[-800:])
    sys.exit("✗ 转换失败")
print("\n用时 %.0f 秒" % (time.time() - t0))

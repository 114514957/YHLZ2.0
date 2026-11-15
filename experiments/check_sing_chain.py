# -*- coding: utf-8 -*-
"""检查翻唱链路：状态 API / GPU 占用 / 相关进程 / 日志。"""
from __future__ import annotations

import glob
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

print("=== 1. /sing/status ===")
try:
    with OPENER.open("http://127.0.0.1:8321/sing/status", timeout=15) as r:
        d = json.loads(r.read().decode())
    print(json.dumps(d, ensure_ascii=False, indent=1)[:900])
except Exception as ex:  # noqa: BLE001
    print("   失败：%s: %s" % (type(ex).__name__, ex))

print("\n=== 2. GPU ===")
out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,"
                      "utilization.gpu", "--format=csv,noheader"],
                     capture_output=True, text=True, errors="replace").stdout.strip()
print("   " + out)
apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                       "--format=csv,noheader"], capture_output=True, text=True,
                      errors="replace").stdout.strip()
for ln in apps.splitlines()[:12]:
    print("   " + ln[:120])

print("\n=== 3. 相关进程 ===")
try:
    import psutil
    keys = ("sing", "kim", "mdx", "seed", "demucs", "uvr", "rmvpe", "sovits")
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cl = " ".join(str(x) for x in (p.info.get("cmdline") or [])).lower()
        if any(k in cl for k in keys) and "python" in (p.info.get("name") or "").lower():
            print("   %-6s %s" % (p.info["pid"], cl[:140]))
except Exception as ex:  # noqa: BLE001
    print("   psutil 失败 %s" % ex)

print("\n=== 4. 最近日志 ===")
for pat in ("cache/logs/sing*.log", "cache/logs/*sing*.log", "cache/sing/**/*.log",
            "cache/logs/*.log"):
    fs = sorted(glob.glob(os.path.join(ROOT, pat), recursive=True),
                key=lambda x: -os.path.getmtime(x))[:3]
    for f in fs:
        if "sing" not in os.path.basename(f).lower():
            continue
        age = (time.time() - os.path.getmtime(f)) / 60
        print("\n--- %s（%.1f 分钟前）" % (os.path.basename(f), age))
        t = io.open(f, encoding="utf-8", errors="replace").read()
        print("\n".join(t.splitlines()[-12:])[:1200])

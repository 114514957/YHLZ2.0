# -*- coding: utf-8 -*-
"""验收「adapter → GGUF」：走 HTTP，和界面按钮同一条路。

用小 adapter（v9-gemma-v9t6，34.66 MB）转一个临时文件，验完删掉。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8090"
OUT_DIR = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gguf-lora"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(p, t=30):
    with OPENER.open(BASE + p, timeout=t) as r:
        return json.loads(r.read().decode("utf-8"))


def post(p, body, t=60):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=t) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


VID = "adapter:yuanheng-v9-gemma-v9t6"
OUT = "_convtest-lora.gguf"
path = os.path.join(OUT_DIR, OUT)

print("== 1. 发起转换 %s → %s" % (VID, OUT), flush=True)
code, r = post("/api/convert", {"version_id": VID, "out_name": OUT})
print("   HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)), flush=True)
if code != 200:
    sys.exit(1)

print("\n== 2. 等它跑完", flush=True)
t0 = time.time()
while True:
    time.sleep(2)
    st = get("/api/convert/state")
    print("   %.0fs running=%s ok=%s err=%s" % (time.time() - t0, st["running"],
                                                st["ok"], st["error"] or ""), flush=True)
    if not st["running"]:
        break
    if time.time() - t0 > 900:
        print("   ✗ 超时", flush=True)
        break

print("\n== 3. 产物", flush=True)
if os.path.exists(path):
    print("   文件 %s | %d 字节（%.2f MB）" % (OUT, os.path.getsize(path),
                                             os.path.getsize(path) / 1048576), flush=True)
else:
    print("   ✗ 没有产物", flush=True)

print("\n== 4. 日志尾部", flush=True)
st = get("/api/convert/state")
print("\n".join((st.get("log_tail") or "").splitlines()[-8:]), flush=True)

print("\n== 5. 重扫，确认能被识别成版本", flush=True)
reg = post("/api/scan", {})[1]
names = [v["version"] for v in reg["versions"]]
print("   %s" % ("在列表里 ✔" if "_convtest" in names else "没识别到 ✗"), flush=True)

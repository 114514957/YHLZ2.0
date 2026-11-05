# -*- coding: utf-8 -*-
"""喂对比数据：对 v8 / v7b 各跑一次**冷态** 56 题，走工作台 API。

每个版本：直接调 /api/server/start（它会先停旧的）→ 就绪 → 评测（cold=true）。
不先聊天，保证是冷态。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8090"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(p, t=30):
    with OPENER.open(BASE + p, timeout=t) as r:
        return json.loads(r.read().decode("utf-8"))


def post(p, body, t=120):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=t) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


TARGETS = [
    ("gguf:yuanheng-v8-lora.gguf", "cold_v8"),
    ("gguf:yuanheng-v7b-lora.gguf", "cold_v7b"),
]

for vid, tag in TARGETS:
    print("\n===== %s =====" % vid, flush=True)
    code, r = post("/api/server/start", {"version_id": vid, "port": 8091, "ngl": 99})
    print("  start HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)), flush=True)
    if code != 200:
        continue
    t0 = time.time()
    while True:
        time.sleep(2)
        st = get("/api/server/status")
        sp = st.get("starting") or {}
        if not sp.get("running"):
            if sp.get("error"):
                print("  ✗ %s" % sp["error"], flush=True)
            break
        if time.time() - t0 > 180:
            print("  ✗ 超时", flush=True)
            break
    print("  就绪 %.1fs | %s" % (time.time() - t0, st["own"].get("version")), flush=True)

    code, r = post("/api/eval/start", {"suite": "persona56", "port": 8091,
                                       "tag": tag, "max_tokens": 300, "cold": True})
    print("  eval HTTP %s" % code, flush=True)
    if code != 200:
        continue
    t1 = time.time()
    while True:
        time.sleep(3)
        e = get("/api/eval/state")
        if not e["running"]:
            res = e.get("result") or {}
            print("  %s = %s/%s | %s | %.1fs" % (
                tag, res.get("ok"), res.get("total"),
                json.dumps(res.get("by_cat"), ensure_ascii=False), time.time() - t1), flush=True)
            break

print("\n== 停实例", flush=True)
print("  ", json.dumps(post("/api/server/stop", {})[1], ensure_ascii=False), flush=True)
runs = get("/api/runs")
print("\n== 现在可用记录", flush=True)
for r in runs:
    print("   %-28s %-10s %s/%s cold=%s" % (r["file"][:28], r.get("tag"),
                                            r.get("ok"), r.get("total"), r.get("cold")), flush=True)

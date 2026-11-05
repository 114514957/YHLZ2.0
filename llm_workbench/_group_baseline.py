# -*- coding: utf-8 -*-
"""群聊评测基线（CPU 跑，不占 GPU）。"""
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


print("== 起实例（CPU）", flush=True)
code, r = post("/api/server/start",
               {"version_id": "gguf:yuanheng-v9t6-lora.gguf", "port": 8091, "ngl": 0})
print("   HTTP %s" % code, flush=True)
if code != 200:
    print(r)
    sys.exit(1)
t0 = time.time()
while True:
    time.sleep(2)
    st = get("/api/server/status")
    if not (st.get("starting") or {}).get("running"):
        break
    if time.time() - t0 > 300:
        sys.exit("超时")
print("   就绪 %.1fs" % (time.time() - t0), flush=True)

print("\n== 群聊 12 题（冷态）", flush=True)
code, r = post("/api/eval/start", {"suite": "group", "port": 8091,
                                   "tag": "v9t6_group_cpu", "max_tokens": 300, "cold": True})
print("   eval HTTP %s" % code, flush=True)
t1 = time.time()
while True:
    time.sleep(2)
    e = get("/api/eval/state")
    if not e["running"]:
        res = e.get("result") or {}
        print("   %s/%s | 闸门 %s%s | %.0fs"
              % (res.get("ok"), res.get("total"),
                 "过" if res.get("gate_ok") else "✗",
                 "" if res.get("gate_ok") else " " + ",".join(res.get("gate_fail") or []),
                 time.time() - t1), flush=True)
        print(flush=True)
        for x in res.get("results") or []:
            print("   %-4s %-16s %s | %r"
                  % (x["id"], x.get("q"), "OK  " if x["ok"] else "FAIL",
                     (x.get("answer") or "")[:60]), flush=True)
            if not x["ok"]:
                print("        why: %s" % x.get("why"), flush=True)
        break

print("\n== 停实例", flush=True)
print("  ", json.dumps(post("/api/server/stop", {})[1], ensure_ascii=False), flush=True)

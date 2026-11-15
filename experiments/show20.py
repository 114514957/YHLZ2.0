# -*- coding: utf-8 -*-
"""给老爹看 20 道素材题的原始问答（只出答案，不判分）。"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8090"
VID = "gguf:yuanheng-v9t10-lora.gguf"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(p, t=30):
    with OPENER.open(BASE + p, timeout=t) as r:
        return json.loads(r.read().decode("utf-8"))


def post(p, body, t=180):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=t) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


print("起实例（CPU）…", flush=True)
code, r = post("/api/server/start", {"version_id": VID, "port": 8091, "ngl": 0})
if code != 200:
    sys.exit("起不来：%s %s" % (code, r))
t0 = time.time()
while True:
    time.sleep(2)
    st = get("/api/server/status")
    if not (st.get("starting") or {}).get("running"):
        break
    if time.time() - t0 > 300:
        sys.exit("超时")
print("就绪 %.1fs\n" % (time.time() - t0), flush=True)

code, _ = post("/api/eval/start", {"suite": "material20", "port": 8091,
                                   "tag": "v9t10_20", "max_tokens": 300, "cold": True})
t1 = time.time()
while True:
    time.sleep(2)
    e = get("/api/eval/state")
    if not e["running"]:
        res = e.get("result") or {}
        print("20 道题，用时 %.0f 秒\n" % (time.time() - t1), flush=True)
        for i, x in enumerate(res.get("results") or [], 1):
            print("%2d. 问：%s" % (i, (x.get("q") or "").replace("\n", " ")[:70]))
            print("    答：%s" % (x.get("answer") or "").replace("\n", " ")[:160])
            print()
        break

post("/api/server/stop", {})

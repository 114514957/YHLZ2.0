# -*- coding: utf-8 -*-
"""v9t7 两套评测：56 题人格 + 26 题群聊，全冷态（CPU 跑，不占 GPU）。"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8090"
VID = "gguf:yuanheng-v9t7-lora.gguf"
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


def wait_ready(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = get("/api/server/status")
        if not (st.get("starting") or {}).get("running"):
            return st
        time.sleep(2)
    raise RuntimeError("起服务超时")


def run(suite, tag):
    t0 = time.time()
    code, r = post("/api/eval/start", {"suite": suite, "port": 8091, "tag": tag,
                                       "max_tokens": 300, "cold": True})
    print("  %-9s HTTP %s" % (suite, code), flush=True)
    if code != 200:
        print("   ", r, flush=True)
        return None
    while True:
        time.sleep(3)
        e = get("/api/eval/state")
        if not e["running"]:
            res = e.get("result") or {}
            print("  %-9s %s/%s | %s | 闸门 %s%s | %.0fs"
                  % (suite, res.get("ok"), res.get("total"),
                     json.dumps(res.get("by_cat"), ensure_ascii=False),
                     "过" if res.get("gate_ok") else "✗",
                     "" if res.get("gate_ok") else " " + ",".join(res.get("gate_fail") or []),
                     time.time() - t0), flush=True)
            return res
        time.sleep(0)


print("== 起实例（CPU）", flush=True)
code, r = post("/api/server/start", {"version_id": VID, "port": 8091, "ngl": 0})
print("   HTTP", code, json.dumps(r, ensure_ascii=False), flush=True)
if code != 200:
    sys.exit(1)
st = wait_ready()
print("   就绪 | %s" % st["own"].get("version"), flush=True)

print("\n== 56 题人格", flush=True)
a = run("persona56", "v9t7_56")
print("\n== 26 题群聊", flush=True)
b = run("group", "v9t7_group")

print("\n== 停实例", flush=True)
print("  ", json.dumps(post("/api/server/stop", {})[1], ensure_ascii=False), flush=True)

if a:
    print("\n== 失败题（56）==", flush=True)
    print("   " + ",".join(x["id"] for x in a["results"] if not x["ok"]), flush=True)
if b:
    print("== 失败题（群聊）==", flush=True)
    for x in b["results"]:
        if not x["ok"]:
            print("   %-4s %s" % (x["id"], x.get("why")))

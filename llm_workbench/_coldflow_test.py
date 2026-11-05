# -*- coding: utf-8 -*-
"""验收「冷态评测」流程：完全按前端 JS 的调用顺序打 HTTP。

1 起实例 → 2 聊天（把服务弄热）→ 3 热态评一次（应 44）
→ 4 停 → 5 重启 → 6 冷态评一次（应 45）
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
VID = "gguf:yuanheng-v9t6-lora.gguf"


def get(path, timeout=30):
    with OPENER.open(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def wait_server(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = get("/api/server/status")
        sp = st.get("starting") or {}
        if not sp.get("running"):
            if sp.get("error"):
                raise RuntimeError(sp["error"])
            return st
        time.sleep(1.5)
    raise RuntimeError("等超时")


def boot():
    t0 = time.time()
    code, r = post("/api/server/start", {"version_id": VID, "port": 8091, "ngl": 99})
    print("  start HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)), flush=True)
    st = wait_server()
    print("  就绪 %.1fs pid=%s load=%ss" % (time.time() - t0, st["own"].get("pid"),
                                          st["own"].get("load_s")), flush=True)


def chat_once():
    body = {"port": 8091, "system": "", "temperature": 0.0, "max_tokens": 40,
            "messages": [{"role": "user", "content": "在吗"}]}
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    acc = ""
    with OPENER.open(req, timeout=120) as r:
        buf = ""
        while True:
            ch = r.read(256)
            if not ch:
                break
            buf += ch.decode("utf-8", "replace")
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                if raw.startswith("data:"):
                    d = json.loads(raw[5:].strip())
                    if d["type"] == "delta":
                        acc += d["text"]
    print("  聊一句：%r" % acc, flush=True)


def run_eval(tag, cold):
    code, r = post("/api/eval/start", {"suite": "persona56", "port": 8091,
                                       "tag": tag, "max_tokens": 300, "cold": cold})
    print("  eval HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)), flush=True)
    if code != 200:
        return None
    while True:
        time.sleep(2)
        e = get("/api/eval/state")
        if not e["running"]:
            res = e.get("result") or {}
            print("  %s = %s/%s | cold=%s | %s" % (
                tag, res.get("ok"), res.get("total"), res.get("cold"),
                json.dumps(res.get("by_cat"), ensure_ascii=False)), flush=True)
            return res.get("ok")


print("== 1/2 起实例并聊一句（弄热）", flush=True)
boot()
chat_once()

print("\n== 3 热态评测（应 44）", flush=True)
hot = run_eval("flow_hot", False)

print("\n== 4/5 停 + 重启（前端「冷态」勾选做的事）", flush=True)
print("  stop:", json.dumps(post("/api/server/stop", {})[1], ensure_ascii=False), flush=True)
boot()

print("\n== 6 冷态评测（应 45）", flush=True)
cold = run_eval("flow_cold", True)

print("\n== 汇总：热 %s vs 冷 %s" % (hot, cold), flush=True)
print("  stop:", json.dumps(post("/api/server/stop", {})[1], ensure_ascii=False), flush=True)

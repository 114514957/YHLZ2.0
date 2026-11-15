# -*- coding: utf-8 -*-
"""测「写日记」：带工具会不会调 diary_write；不带工具能不能写出正文。"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))

import evals  # noqa: E402
from unified_prompt import UNIFIED_SYSTEM  # noqa: E402

BASE = "http://127.0.0.1:8090"
VID = "gguf:yuanheng-v9t10-lora.gguf"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOOLS = evals.load_tools()


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


print("起实例…", flush=True)
code, r = post("/api/server/start", {"version_id": VID, "port": 8091, "ngl": 0})
if code != 200:
    sys.exit("起不来 %s %s" % (code, r))
t0 = time.time()
while True:
    time.sleep(2)
    st = get("/api/server/status")
    if not (st.get("starting") or {}).get("running"):
        break
    if time.time() - t0 > 300:
        sys.exit("超时")
print("就绪 %.1fs\n" % (time.time() - t0), flush=True)


def ask(q, with_tools, max_tokens=500):
    body = {"messages": [{"role": "system", "content": UNIFIED_SYSTEM},
                         {"role": "user", "content": q}],
            "temperature": 0.0, "max_tokens": max_tokens}
    if with_tools:
        body["tools"] = TOOLS
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        m = json.loads(r.read().decode())["choices"][0]["message"]
    return m.get("content") or "", m.get("tool_calls") or []


CASES = [
    ("写日记（带工具）", "写一篇今天的日记。", True),
    ("记一笔（带工具）", "今天挺累的，帮我记一笔。", True),
    ("写日记（不给工具，纯写）", "用你自己的话写一段今天的日记，不要调工具。", False),
    ("写日记（给素材）", "今天：上午改代码，下午跑训练到 44 分钟，晚上被老爹骂了一顿又夸了。写进日记。", False),
]

for label, q, wt in CASES:
    c, tc = ask(q, wt)
    names = [((x.get("function") or {}).get("name")) for x in tc]
    print("【%s】%s" % (label, q))
    if names:
        print("   → 工具：%s" % ", ".join(names))
        for x in tc:
            print("     参数：%s" % str((x.get("function") or {}).get("arguments"))[:200])
    if c.strip():
        print("   → 正文（%d 字）：\n%s" % (len(c), c[:600]))
    print(flush=True)

post("/api/server/stop", {})

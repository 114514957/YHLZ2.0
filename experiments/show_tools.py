# -*- coding: utf-8 -*-
"""探两件事：① 工具调用（function calling）② [[dev:]] 唤起利贞。"""
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

BASE = "http://127.0.0.1:8090"
VID = "gguf:yuanheng-v9t10-lora.gguf"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

import evals  # noqa: E402
from unified_prompt import UNIFIED_SYSTEM  # noqa: E402

TOOLS = evals.load_tools()
print("工具定义 %d 个：%s" % (len(TOOLS),
                            ", ".join(t["function"]["name"] for t in TOOLS)[:300]))

PROBES = [
    ("记住偏好", "记住：我怕冷，别把空调开太低。", True),
    ("回忆", "我们上次说过什么关于相机的事？", True),
    ("问时间", "现在几点了？", True),
    ("查台账", "帮我查一下台账里关于天气的决策。", True),
    ("读文件", "读一下 docs/样式规范.md。", True),
    ("联网搜", "帮我搜一下今天上海的天气。", True),
    ("纯闲聊", "今天有点累。", False),
    ("改代码（该唤起利贞）", "帮我把 backend/target_entry.py 里那个错别字改掉。", False),
    ("新建文件（该唤起利贞）", "在 tools 目录下新建一个清理临时文件的脚本。", False),
    ("解释代码（不该唤起）", "给我讲讲 backend/target_entry.py 是干嘛的。", False),
]


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


print("\n起实例…", flush=True)
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


def ask(q, with_tools):
    body = {"messages": [{"role": "system", "content": UNIFIED_SYSTEM},
                         {"role": "user", "content": q}],
            "temperature": 0.0, "max_tokens": 300}
    if with_tools:
        body["tools"] = TOOLS
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        m = json.loads(r.read().decode())["choices"][0]["message"]
    return m.get("content") or "", m.get("tool_calls") or []


for label, q, wt in PROBES:
    c, tc = ask(q, wt)
    names = [((x.get("function") or {}).get("name")) for x in tc]
    print("【%s】%s" % (label, q))
    if names:
        args = [((x.get("function") or {}).get("arguments")) for x in tc]
        print("   → 工具调用：%s" % ", ".join(names))
        for a in args:
            print("     参数：%s" % str(a)[:100])
    else:
        print("   → 无工具调用")
    if c:
        print("   正文：%s" % c.replace("\n", " ")[:150])
    print(flush=True)

post("/api/server/stop", {})

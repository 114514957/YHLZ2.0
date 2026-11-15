# -*- coding: utf-8 -*-
"""多采样：同一问题问 6 次（每次清会话），看长度分布，判断"塌成电报体"是不是真的。"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8321"


def post(path: str, payload: dict | None = None) -> None:
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload or {}, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=20) as r:
        r.read()


def ask(text: str) -> str:
    req = urllib.request.Request(BASE + "/talk",
                                 data=json.dumps({"text": text}, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    ans = ""
    with OPENER.open(req, timeout=240) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            if ev.get("type") == "turn_done":
                ans = str(ev.get("text") or "")
    return ans.strip()


QS = ["今天有点累", "说说你最近在想什么", "你觉得我该不该早点睡"]
N = 3
print("每个问题采样 %d 次（每次先清会话）\n" % N)
all_len = []
for q in QS:
    lens = []
    print("问：%s" % q)
    for i in range(N):
        post("/reset")
        a = ask(q)
        lens.append(len(a))
        print("   %d) %2d 字：%s" % (i + 1, len(a), a))
    all_len += lens
    print("   平均 %.1f 字\n" % (sum(lens) / len(lens)))

print("全部 %d 次：平均 %.1f 字｜最短 %d｜最长 %d"
      % (len(all_len), sum(all_len) / len(all_len), min(all_len), max(all_len)))

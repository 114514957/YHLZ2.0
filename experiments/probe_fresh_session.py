# -*- coding: utf-8 -*-
"""清会话后重测：排除"她模仿自己上几句"的干扰。

先 POST /reset（换新会话），再问三题，看是不是真的塌缩。
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")
from backend.text_scrub import has_dash, violations  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8321"

# 1) 重置会话
for path in ("/reset", "/session"):
    try:
        req = urllib.request.Request(BASE + path, data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=20) as r:
            print("重置 %s → %s %s" % (path, r.status, r.read()[:120]))
            break
    except Exception as ex:  # noqa: BLE001
        print("重置 %s 失败：%s" % (path, type(ex).__name__))


def ask(text: str) -> str:
    body = json.dumps({"text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/talk", data=body,
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
    return ans


for q in ["今天有点累", "说说你最近在想什么", "你觉得我该不该早点睡"]:
    a = ask(q)
    print("\n问：%s" % q)
    print("答：%s" % a.strip())
    print("体检：%d 字｜破折号 %s｜命中 %s"
          % (len(a.strip()), "有" if has_dash(a) else "无",
             "、".join(violations(a)) or "无"))

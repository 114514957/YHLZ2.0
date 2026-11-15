# -*- coding: utf-8 -*-
"""端到端验工作台提示词模块（走 HTTP，不直接调函数）。"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8321"


def get(path):
    with OPENER.open(BASE + path, timeout=25) as r:
        return json.loads(r.read().decode())


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=25) as r:
        return json.loads(r.read().decode())


b0 = get("/prompt/preview?public=0")
print("改前：%d 字｜约 %d token" % (b0["chars"], b0["approx_tokens"]))

r = post("/prompt/set", {"key": "STYLE_HABIT_CLAUSE",
                         "text": "（HTTP 测试）被问回来没有，就答『回来了』。"})
print("保存：", r)

b1 = get("/prompt/preview?public=0")
print("改后：%d 字｜含覆盖：%s" % (b1["chars"], "HTTP 测试" in b1["text"]))

st = get("/prompt/blocks")
hit = [x for x in st["blocks"] if x["key"] == "STYLE_HABIT_CLAUSE"][0]
print("列表标记：changed=%s｜current %d 字（默认 %d）"
      % (hit["changed"], len(hit["current"]), len(hit["default"])))

print("还原：", post("/prompt/set", {"key": "STYLE_HABIT_CLAUSE", "text": ""}))
b2 = get("/prompt/preview?public=0")
print("还原后：%d 字｜残留：%s" % (b2["chars"], "HTTP 测试" in b2["text"]))

print("全部还原：", post("/prompt/reset", {}))

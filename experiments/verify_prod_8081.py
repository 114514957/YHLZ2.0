# -*- coding: utf-8 -*-
"""验生产 8081：挂的是哪版 LoRA、说话像不像丙。"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

log = os.path.join(YH, "cache", "logs", "llama-server.log")
t = io.open(log, encoding="utf-8", errors="replace").read()
hit = [ln for ln in t.splitlines() if "--lora" in ln or "lora" in ln.lower()][-3:]
print("== llama 启动参数里的 LoRA ==")
for h in hit:
    print("   %s" % h[:200])
print("   日志里出现 dpo2：%s" % ("dpo2" in t[-4000:]))

print("\n== /health ==")
try:
    with OPENER.open("http://127.0.0.1:8081/health", timeout=5) as r:
        print("   %s %s" % (r.status, r.read()[:120].decode("utf-8", "replace")))
except Exception as ex:  # noqa: BLE001
    print("   不可用：%s" % ex)
    sys.exit(1)

print("\n== 让她说两句（判是不是丙）==")
for q in ("在吗", "我回来了。", "你刚才怎么那么凶。"):
    body = {"messages": [{"role": "user", "content": q}],
            "max_tokens": 80, "temperature": 0.7}
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=120) as r:
            a = json.loads(r.read().decode())["choices"][0]["message"]["content"]
        print("   问：%s\n   答：%s" % (q, a.strip().replace("\n", " ")[:120]))
    except Exception as ex:  # noqa: BLE001
        print("   失败：%s" % ex)

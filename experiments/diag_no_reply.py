# -*- coding: utf-8 -*-
"""诊断「发了消息没回复」：逐段看桥、daemon、模型。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def tail(p: str, n: int = 14, strip_ansi: bool = True) -> str:
    if not os.path.exists(p):
        return "（无文件 %s）" % p
    age = (time.time() - os.path.getmtime(p)) / 60
    t = io.open(p, encoding="utf-8", errors="replace").read()
    if strip_ansi:
        t = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", t)
    lines = [x for x in t.splitlines() if x.strip()]
    return "（%.0f 分钟前最后写入）\n%s" % (age, "\n".join(lines[-n:]))


print("=== 1. 桥日志（收到消息了吗）===")
print(tail(os.path.join(YH, "cache", "qq_bridge", "lite", "bridge.log"), 12))

print("\n=== 2. daemon 日志 ===")
print(tail(os.path.join(YH, "cache", "logs", "daemon.log"), 12))

print("\n=== 3. 模型 8081 ===")
t0 = time.time()
try:
    body = {"messages": [{"role": "system", "content": "【身份】你是元亨。"},
                         {"role": "user", "content": "在吗"}],
            "max_tokens": 40, "temperature": 0.2}
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    a = d["choices"][0]["message"]["content"]
    print("   ✅ 回了（%.1f 秒）：%s" % (time.time() - t0, a.strip()[:80]))
except Exception as ex:  # noqa: BLE001
    print("   ❌ 不回：%s: %s" % (type(ex).__name__, str(ex)[:150]))

print("\n=== 4. daemon 8321 ===")
for path in ("/health", "/"):
    try:
        with OPENER.open("http://127.0.0.1:8321" + path, timeout=8) as r:
            print("   %-8s %s %s" % (path, r.status, r.read()[:80]))
        break
    except Exception as ex:  # noqa: BLE001
        print("   %-8s ❌ %s" % (path, type(ex).__name__))

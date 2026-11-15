# -*- coding: utf-8 -*-
"""测 DeepSeek 主链路通不通（决定她到底跑在哪个模型上）。"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.env_loader import ensure_env_loaded  # noqa: E402

ensure_env_loaded()
key = os.getenv("DEEPSEEK_API_KEY", "")
base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
print("key 长度 %d｜base %s" % (len(key), base))

print("\n① DNS / TCP")
try:
    host = "api.deepseek.com"
    ip = socket.gethostbyname(host)
    s = socket.create_connection((host, 443), timeout=8)
    s.close()
    print("   %s → %s:443 可达 ✅" % (host, ip))
except Exception as ex:  # noqa: BLE001
    print("   不可达 ❌ %s: %s" % (type(ex).__name__, ex))

print("\n② 实际调一次（会花钱，1 个 token 级别）")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
body = json.dumps({"model": "deepseek-chat", "max_tokens": 8,
                   "messages": [{"role": "user", "content": "说一个字"}]}).encode()
req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body,
                             headers={"Content-Type": "application/json",
                                      "Authorization": "Bearer " + key})
t0 = time.time()
try:
    with OPENER.open(req, timeout=40) as r:
        d = json.loads(r.read().decode())
    print("   ✅ 通（%.1f 秒）｜返回：%s"
          % (time.time() - t0,
             str(d["choices"][0]["message"]["content"])[:40]))
except Exception as ex:  # noqa: BLE001
    print("   ❌ 不通（%.1f 秒）｜%s: %s" % (time.time() - t0, type(ex).__name__,
                                          str(ex)[:200]))

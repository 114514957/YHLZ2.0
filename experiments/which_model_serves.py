# -*- coding: utf-8 -*-
"""实证：daemon 的一轮对话，究竟打到云端还是本地 8081？

做法：记下 llama-server 日志大小 → 调 daemon /turn → 再看日志大小。
本地模型若被调用，llama-server 会写请求日志。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
LOG = os.path.join(ROOT, "cache", "logs", "llama-server.log")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def logsize():
    try:
        return os.path.getsize(LOG)
    except Exception:  # noqa: BLE001
        return -1


def ask(text: str) -> tuple[str, float]:
    t0 = time.time()
    # /turn 有渠道鉴权（channel_auth）：source 必须与 channel 匹配，缺失即 403。
    body = json.dumps({"text": text, "channel": "console", "source": "console"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8321/turn", data=body,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    return str(d.get("answer") or d.get("reply") or d)[:160], time.time() - t0


before = logsize()
print("调用前 llama-server 日志：%d 字节" % before)

ans, dt = ask("用一句话告诉我，你现在跑在哪上面。")
print("daemon 回的：%s" % ans)
print("耗时 %.1f 秒" % dt)

time.sleep(2)
after = logsize()
print("\n调用后日志：%d 字节｜增长 %d" % (after, after - before))
if after - before > 0:
    with open(LOG, "rb") as f:
        f.seek(max(0, after - 1500))
        tail = f.read().decode("utf-8", "replace")
    print("本地 llama 最后日志片段：")
    print("   " + tail[-600:].replace("\n", "\n   "))
else:
    print("\n→ 本地 8081 **没有收到请求**：这一轮是云端（DeepSeek）答的。")

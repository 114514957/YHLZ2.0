# -*- coding: utf-8 -*-
"""实证：QQ 频道的一轮，走云端还是本地？(不真发到 QQ，只让 daemon 生成)"""
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


def size():
    try:
        return os.path.getsize(LOG)
    except Exception:  # noqa: BLE001
        return -1


def turn(channel, text):
    body = json.dumps({"text": text, "channel": channel,
                       "source": "qq_bridge"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8321/turn", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with OPENER.open(req, timeout=240) as r:
        d = json.loads(r.read().decode())
    return d, time.time() - t0


for ch, label in (("qq_g1121723665", "QQ群(AI对话)"),
                  ("qq_p2258374446", "QQ私聊(老爹)")):
    b = size()
    try:
        d, dt = turn(ch, "一句话：你现在用的是哪个模型？")
    except Exception as ex:  # noqa: BLE001
        print("%s → 调用失败 %s" % (label, ex))
        continue
    time.sleep(2)
    a = size()
    ans = str(d.get("answer") or d.get("reply") or "")[:100].replace("\n", " ")
    print("\n%s（%s）" % (label, ch))
    print("   答：%s" % ans)
    print("   耗时 %.1f 秒｜本地 llama 日志增长 %d 字节 → %s"
          % (dt, a - b, "本地模型" if a - b > 0 else "云端模型（本地没被打）"))

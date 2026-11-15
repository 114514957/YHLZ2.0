# -*- coding: utf-8 -*-
"""给 eval56_28.py 加云端支持：`--provider cloud` 时改走 llm_router。

只替换发请求那一小段（`call()` 的 HTTP 部分），判分逻辑一字不动。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "experiments", "eval56_28.py")
t = io.open(P, encoding="utf-8").read()

OLD = '''    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=300) as r:
        d = json.loads(r.read().decode())'''

NEW = '''    # 2026-11-15（台账 1245）：本地 llama 已下线，评测必须能打云端。
    # `port == 0` 表示走 llm_router（cloud）；否则仍打本地 OpenAI 兼容端点。
    if port == 0:
        from backend import llm_router as _R
        d = _R.chat(msgs, tools=tools or None, temperature=0.0,
                    max_tokens=max_tokens, channel="eval", retries=3)
    else:
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                     data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=300) as r:
            d = json.loads(r.read().decode())'''

assert t.count(OLD) == 1, "定位失败：找不到请求段"
t = t.replace(OLD, NEW)

OLD2 = '''    ap.add_argument("--port", type=int, default=8081)'''
NEW2 = '''    ap.add_argument("--port", type=int, default=8081,
                    help="0 = 走 llm_router（云端）")
    ap.add_argument("--provider", default="",
                    help="cloud / local；给 cloud 等价于 --port 0")'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

OLD3 = '''    print("评测 tag=%s｜锚点=%s(%s)｜port=%d"
          % (a.tag, "开" if a.anchor else "关", a.anchor_mode, a.port))'''
NEW3 = '''    port = 0 if str(a.provider).lower() == "cloud" else a.port
    print("评测 tag=%s｜锚点=%s(%s)｜port=%d%s"
          % (a.tag, "开" if a.anchor else "关", a.anchor_mode, port,
             "（云端 llm_router）" if port == 0 else ""))'''
assert t.count(OLD3) == 1
t = t.replace(OLD3, NEW3)
t = t.replace("    res = run(a.port, a.anchor, a.max_tokens, a.anchor_mode)",
              "    res = run(port, a.anchor, a.max_tokens, a.anchor_mode)")

io.open(P, "w", encoding="utf-8").write(t)
print("已改 eval56_28.py：支持 --provider cloud（走 llm_router）")

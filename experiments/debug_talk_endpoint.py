# -*- coding: utf-8 -*-
"""先看 /talk 到底回了什么（原始响应），再决定走哪条路。"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

for url, payload in (
        ("http://127.0.0.1:8321/talk", {"text": "在吗"}),
        ("http://127.0.0.1:8321/api/talk", {"text": "在吗"}),
):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=60) as r:
            raw = r.read()[:400]
            print("%s → %s" % (url, r.status))
            print("   %r" % raw)
    except urllib.error.HTTPError as ex:
        print("%s → HTTP %s" % (url, ex.code))
        print("   %r" % ex.read()[:400])
    except Exception as ex:  # noqa: BLE001
        print("%s → %s: %s" % (url, type(ex).__name__, ex))
    print()

# -*- coding: utf-8 -*-
"""验证：napcat_window 动作 + QQ 页签是否就位。"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(p: str) -> dict:
    with OPENER.open("http://127.0.0.1:8321" + p, timeout=30) as f:
        return json.loads(f.read().decode())


def post(p: str, body: dict) -> dict:
    r = urllib.request.Request("http://127.0.0.1:8321" + p,
                               data=json.dumps(body, ensure_ascii=False).encode(),
                               headers={"Content-Type": "application/json"})
    with OPENER.open(r, timeout=60) as f:
        return json.loads(f.read().decode())


print("napcat_window →", str(post("/control", {"action": "napcat_window"}))[:200])
time.sleep(12)
q = (get("/state") or {}).get("qq") or {}
print("登录：online=%s ws=%s" % (q.get("online"), q.get("ws")))

with OPENER.open("http://127.0.0.1:8321/", timeout=20) as f:
    html = f.read().decode("utf-8", "replace")
checks = {
    'QQ 页签': 'data-panel="qq"' in html,
    "打开登录窗口按钮": "qq-win" in html,
    "状态显示": "qq-state" in html,
    "搬卡脚本": "moveCards" in html,
    "检查登录状态": "qq-check" in html,
}
for k, v in checks.items():
    print("  %-12s %s" % (k, "✅" if v else "❌"))

# -*- coding: utf-8 -*-
"""把积压的重复通知标成 skipped，避免老爹一登录被刷屏。

做前先停桥（它同时写这个文件），改完再起。只动 status=pending/sending 的行。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(YH, ".venv", "Scripts", "python.exe")
CTL = os.path.join(YH, "tools", "qq_bridge_control.py")
NOTICES = os.path.join(YH, "cache", "qq_bridge", "lite", "notices.jsonl")


def run(args, t=180):
    r = subprocess.run([PY] + args, cwd=YH, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=t)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


print("[1] 停桥（不动 NapCat）")
o, e, _ = run([CTL, "stop", "--no-napcat"])
print("   " + (o or e)[:200])

print("\n[2] 标记积压通知")
rows = [json.loads(x) for x in io.open(NOTICES, encoding="utf-8") if x.strip()]
n = 0
for r in rows:
    if r.get("status") in ("pending", "sending"):
        r["status"] = "skipped"
        r["last_error"] = "superseded: 登录时清理重复通知 (2026-11-13)"
        r["updated_at"] = time.time()
        n += 1
tmp = NOTICES + ".tmp"
with io.open(tmp, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
os.replace(tmp, NOTICES)
print("   标记 %d 条为 skipped｜总 %d 条" % (n, len(rows)))

print("\n[3] 起桥")
o, e, rc = run([CTL, "start", "--no-napcat", "--wait-bridge", "40"])
print("   " + (o or e)[:400])

print("\n[4] 复查")
o, _e, _ = run([CTL, "status"])
try:
    d = json.loads(o)
    print("   desired=%s｜bridge alive=%s｜ws=%s｜online=%s"
          % (d.get("desired"), d["bridge"].get("alive"),
             d["bridge"].get("ws_state"), d["bridge"].get("account_online")))
    print("   通知：%s" % d.get("notices", {}).get("by_status"))
except Exception as ex:  # noqa: BLE001
    print("   解析失败：%s" % ex)

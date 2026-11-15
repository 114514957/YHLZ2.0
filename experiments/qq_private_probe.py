# -*- coding: utf-8 -*-
"""诊断私信通道：好友列表 → 主动发一条 → 等他回（收侧验证）。"""
from __future__ import annotations

import asyncio
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

from backend import qq_group_admin as A  # noqa: E402

MASTER = "2258374446"


def call(action, params=None, timeout=10.0):
    try:
        m = asyncio.run(A._call(action, params or {}, timeout))
        return m
    except Exception as ex:  # noqa: BLE001
        return {"status": "error", "error": "%s: %s" % (type(ex).__name__, ex)}


print("① get_friend_list")
m = call("get_friend_list")
if m.get("status") == "ok":
    fs = m.get("data") or []
    print("   好友 %d 个" % len(fs))
    hit = [f for f in fs if str(f.get("user_id")) == MASTER]
    print("   主人在好友里：%s" % ("是 ✅" if hit else "否 ❌"))
    if hit:
        print("   昵称：%s" % hit[0].get("nickname"))
else:
    print("   失败：%s" % json.dumps(m, ensure_ascii=False)[:200])

print("\n② 主动发一条私信给主人")
m = call("send_private_msg", {"user_id": int(MASTER),
                              "message": "【自检】私信通道测试，收到请随便回一句。"})
print("   " + json.dumps({k: m.get(k) for k in ("status", "retcode", "data", "error")},
                         ensure_ascii=False)[:300])

print("\n③ 等 75 秒，看有没有 private 事件进来（请回一句）")
t0 = time.time()
log = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\tmp\qq_events.log"
before = 0
try:
    before = len(open(log, encoding="utf-8", errors="replace").read().splitlines())
except Exception:  # noqa: BLE001
    pass
found = []
while time.time() - t0 < 75:
    try:
        lines = open(log, encoding="utf-8", errors="replace").read().splitlines()[before:]
    except Exception:  # noqa: BLE001
        lines = []
    for ln in lines:
        if '"message_type":"private"' in ln and ln not in found:
            found.append(ln)
    if found:
        break
    time.sleep(3)

print("   私信事件：%d 条" % len(found))
for ln in found[:3]:
    print("   " + ln[:320])
if not found:
    print("   （75 秒内没收到）")

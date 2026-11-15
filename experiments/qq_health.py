# -*- coding: utf-8 -*-
"""开工前体检：桥/NapCat/模型服务端口、进程、状态文件。"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(1.2)
    try:
        s.connect((host, port))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


print("== 端口 ==")
for p, name in ((3001, "NapCat WS"), (8081, "元亨模型 HTTP"), (8321, "?"),
                (8348, "?"), (6006, "面板")):
    print("   %-16s %-5d %s" % (name, p, "OPEN" if port_open(p) else "closed"))

print("\n== 进程 ==")
out = subprocess.run(["wmic", "process", "get", "ProcessId,Name,CommandLine", "/format:list"],
                     capture_output=True, text=True, errors="replace").stdout
keys = ("qq_bot", "napcat", "target_daemon", "llama-server", "bridge", "qqwatch")
hits = [ln.strip() for ln in out.splitlines()
        if any(k in ln.lower() for k in keys) and "CommandLine" in ln]
print("   命中 %d 条" % len(hits))
for hnt in hits[:8]:
    print("   %s" % hnt[:150])

print("\n== 状态文件 ==")
for rel in (r"cache\qq_bridge\lite\bridge_status.json",
            r"cache\qq_bridge\lite\delivery_status.json",
            r"cache\qq_bridge\lite\desired_state.json",
            r"cache\qq_bridge\lite\qq_state.json"):
    p = os.path.join(YH, rel)
    if not os.path.exists(p):
        print("   %-46s 缺" % rel)
        continue
    try:
        d = json.load(io.open(p, encoding="utf-8"))
        print("   %-46s %s" % (rel, json.dumps(d, ensure_ascii=False)[:170]))
    except Exception as ex:  # noqa: BLE001
        print("   %-46s 解析失败 %s" % (rel, ex))

print("\n== pid 文件 ==")
for rel in (r"cache\qq_bridge\lite\napcat.pid", r"cache\qq_bridge\lite\bridge.pid"):
    p = os.path.join(YH, rel)
    print("   %-46s %s" % (rel, open(p).read().strip() if os.path.exists(p) else "缺"))

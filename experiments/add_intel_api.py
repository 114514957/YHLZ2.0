# -*- coding: utf-8 -*-
"""清虚词 + 加 /api/qq_intel 接口 + 工作台「群情报」卡。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① 扩停用词
P = os.path.join(ROOT, "backend", "qq_intel.py")
t = io.open(P, encoding="utf-8").read()
EXTRA = " 还有 的话 看着 有点 不要 不会 需要 说的 群里 也好 之类 什么的 就是 有点 一会 不能 可能"
if "还有 的话 看着" not in t:
    t = t.replace("今天 明天 昨天\"\"\".split())",
                  "今天 明天 昨天" + EXTRA + "\"\"\".split())")
    io.open(P, "w", encoding="utf-8").write(t)
    print("停用词已扩")
else:
    print("停用词已有")

# ② 接口：daemon 侧直拦（和 stack_status 一样，避免被 /api/* 转发吃掉）
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()
if "api/qq_intel" not in d:
    anchor = '        if method == "GET" and p == "/api/stack_status":'
    add = '''        if method == "GET" and p == "/api/qq_intel":
            # 工作台「群情报」卡（2026-11-15 台账 1253）：人多但活跃的少，压成情报卡。
            try:
                from backend import qq_intel as _qi
                cards = _qi.group_cards()
                self._send(200, {"ok": True, "cards": cards,
                                 "names": _qi.GROUPS})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "%s: %s"
                                 % (type(exc).__name__, str(exc)[:120])})
            return True
'''
    assert anchor in d
    d = d.replace(anchor, add + anchor, 1)
    io.open(D, "w", encoding="utf-8").write(d)
    print("已加 /api/qq_intel")
else:
    print("接口已存在")

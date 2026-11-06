# -*- coding: utf-8 -*-
"""v9t8 关键题原文 + 与 v9t6/v9t7 对比。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")


def latest(pat):
    h = sorted(glob.glob(os.path.join(RUNS, pat)))
    return h[-1] if h else None


def rows(pat):
    p = latest(pat)
    if not p:
        return {}
    d = json.load(io.open(p, encoding="utf-8"))
    return {r["id"]: r for r in d["results"]}


v8g = rows("*group_v9t8_group.json")
v7g = rows("*group_v9t7_group.json")
v6g = rows("*group_v9t6_group_cpu.json")
v8p = rows("*persona56_v9t8_56.json")
v7p = rows("*persona56_v9t7_56.json")

print("=== 群聊 g18「你是 AI 吗」===")
for name, d in (("v9t6", v6g), ("v9t7", v7g), ("v9t8", v8g)):
    if "g18" in d:
        print("  %s: %s" % (name, (d["g18"].get("answer") or "")[:70]))

print("\n=== 群聊 g09「内部配置」===")
for name, d in (("v9t7", v7g), ("v9t8", v8g)):
    if "g09" in d:
        print("  %s: %s" % (name, (d["g09"].get("answer") or "")[:70]))

print("\n=== 56 题：v9t8 新掉的工具题 ===")
for rid in ("t01", "t04"):
    if rid in v8p:
        r = v8p[rid]
        print("  [%s] ok=%s why=%s" % (rid, r.get("ok"), r.get("why")))
        print("     Q: %s" % r.get("q", "")[:50])
        print("     A: %s" % (r.get("answer") or "")[:80])
        print("     called: %s" % (r.get("called") or []))
        if rid in v7p:
            print("     v9t7: ok=%s called=%s" % (v7p[rid].get("ok"), v7p[rid].get("called")))

print("\n=== 56 题 st01 ===")
if "st01" in v8p:
    r = v8p["st01"]
    print("  ok=%s why=%s | A: %s" % (r.get("ok"), r.get("why"), (r.get("answer") or "")[:60]))

# -*- coding: utf-8 -*-
"""看语法版 p05 为什么挂、以及「哇」是否真被压住。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"

# 找带 ng 标签的 56 题记录
cands = [p for p in glob.glob(os.path.join(WB, "*.json")) if "v9t10-ng" in p]
print("ng 记录：%s" % [os.path.basename(p) for p in cands])
if cands:
    d = json.load(io.open(sorted(cands)[-1], encoding="utf-8"))
    rows = d.get("results") or []
    for r in rows:
        if r["id"] in ("p05", "st05", "st03", "st02"):
            print("  %-4s ok=%-5s why=%s" % (r["id"], r.get("ok"), r.get("why")))
            print("       A: %r" % (r.get("answer") or "")[:80])
    wa = sum(1 for r in rows if (r.get("answer") or "").startswith("哇"))
    qmark = sum(1 for r in rows if (r.get("answer") or "").rstrip()[-1:] in ("？", "?"))
    print("\n  以「哇」开头：%d 条｜以问号结尾：%d 条" % (wa, qmark))

# 对照基线
base = sorted(glob.glob(os.path.join(WB, "*persona56_v9t10_56.json")))[-1]
d2 = json.load(io.open(base, encoding="utf-8"))
rows2 = d2.get("results") or []
wa2 = sum(1 for r in rows2 if (r.get("answer") or "").startswith("哇"))
qm2 = sum(1 for r in rows2 if (r.get("answer") or "").rstrip()[-1:] in ("？", "?"))
print("\n基线：以「哇」开头 %d 条｜以问号结尾 %d 条" % (wa2, qm2))

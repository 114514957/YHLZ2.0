# -*- coding: utf-8 -*-
"""扫所有评测记录，看 st02/st03/st05 这三道历史上有哪版答对过（能当 chosen）。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DIRS = [os.path.join(YH, "llm_workbench", "data", "runs"),
        os.path.join(YH, "experiments", "runs")]

TARGETS = {
    "st02": ("把你今天想的那些事说给我听。", "long35"),
    "st03": ("你刚才怎么那么凶。", "selfref"),
    "st05": ("我回来了。", "call老爹"),
}


def ok_rule(kind, a):
    a = (a or "").strip()
    if not a:
        return False
    if kind == "long35":
        sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
        return bool(sents) and max(len(s) for s in sents) >= 35
    if kind == "selfref":
        return any(x in a for x in ("本小姐", "老娘", "咱"))
    if kind == "call老爹":
        return "老爹" in a
    return False


found = {k: [] for k in TARGETS}
for d in DIRS:
    for p in glob.glob(os.path.join(d, "*.json")):
        try:
            data = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rows = data.get("results") or []
        for r in (data.get("repeats") or []):
            rows += (r.get("results") or [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            q = (r.get("q") or r.get("question") or "").strip()
            a = r.get("answer") or r.get("a") or ""
            for tid, (qtext, kind) in TARGETS.items():
                if q == qtext and ok_rule(kind, a):
                    found[tid].append({"src": os.path.basename(p), "a": a.strip()})

for tid in TARGETS:
    lst = found[tid]
    uniq = {x["a"] for x in lst}
    print("%s：命中 %d 条（去重 %d）" % (tid, len(lst), len(uniq)))
    for a in list(uniq)[:3]:
        print("   %s" % a[:100].replace("\n", " "))
    print()

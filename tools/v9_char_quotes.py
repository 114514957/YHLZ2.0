#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为每个角色挑 3 条"短而有辨识度"的台词示例（≤60 字），供研读样张引用。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "char_voice_quotes.json")


def pick(lines: list[str], n: int = 3) -> list[str]:
    """优先：短句（12-55字）、带语气（？/！/…）、不重复。"""
    cand = []
    for x in lines:
        x = x.strip()
        if not (10 <= len(x) <= 58):
            continue
        if re.search(r"[“”「」]", x):
            continue
        score = 0
        if "？" in x:
            score += 2
        if "！" in x:
            score += 1
        if "…" in x:
            score += 1
        if "，" in x:
            score += 1
        cand.append((score, len(x), x))
    cand.sort(key=lambda t: (-t[0], t[1]))
    out, seen = [], set()
    for _, _, x in cand:
        key = x[:8]
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
        if len(out) >= n:
            break
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data: dict[str, list[str]] = {}
    for p in glob.glob(os.path.join(CACHE, "book_dialogue_v4_*.json")):
        d = json.load(io.open(p, encoding="utf-8"))
        for name, rows in d["samples"].items():
            data.setdefault(name, []).extend(l for _, l in rows)
    res = {n: pick(v) for n, v in data.items()}
    for n, qs in res.items():
        print("\n【%s】" % n)
        for q in qs:
            print("   · %s" % q)
    json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

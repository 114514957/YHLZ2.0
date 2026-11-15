# -*- coding: utf-8 -*-
"""口头禅命中审计：统计她的回复里这些拐杖词出现多频繁（基线）。

扫描：cache/sessions/*.json（QQ 会话）+ cache/qq_daily/*.jsonl（按天落盘）
输出：每组命中次数、每千条回复命中率、最高频的具体命中文本。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
CFG = os.path.join(ROOT, "config", "style_bans.json")


def load_bans() -> dict[str, list[re.Pattern]]:
    d = json.load(io.open(CFG, encoding="utf-8"))
    out = {}
    for g, pats in (d.get("groups") or {}).items():
        c = []
        for p in pats:
            try:
                c.append(re.compile(p))
            except re.error as ex:
                print("   正则有问题：%s → %s" % (p, ex))
        out[g] = c
    return out


def replies() -> list[str]:
    """取她的回复文本（assistant 侧）。"""
    texts: list[str] = []
    for p in glob.glob(os.path.join(ROOT, "cache", "sessions", "qq_*.json")):
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        msgs = d if isinstance(d, list) else (d.get("messages") or d.get("history") or [])
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            if role not in ("assistant", "元亨"):
                continue
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                texts.append(c)
    for p in glob.glob(os.path.join(ROOT, "cache", "qq_daily", "*.jsonl")):
        for ln in io.open(p, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if r.get("role") == "assistant" and str(r.get("text") or "").strip():
                texts.append(str(r["text"]))
    return texts


bans = load_bans()
rs = replies()
print("扫描到她的回复：%d 条\n" % len(rs))
if not rs:
    sys.exit("没有可统计的回复（先跑一会儿或检查 sessions 路径）")

total_hits = 0
hit_examples: dict[str, Counter] = defaultdict(Counter)
for g, pats in bans.items():
    g_hits = 0
    g_msgs = 0
    for t in rs:
        hit = False
        for p in pats:
            m = p.search(t)
            if m:
                hit = True
                hit_examples[g][m.group(0)] += 1
        if hit:
            g_msgs += 1
            g_hits += 1
    total_hits += g_hits
    print("%-26s 命中 %4d 条（占 %.1f%%）" % (g, g_hits, 100 * g_hits / len(rs)))
    for txt, n in hit_examples[g].most_common(4):
        print("      「%s」×%d" % (txt[:24], n))

print("\n合计：%d / %d 条回复命中过至少一个拐杖词（%.1f%%）"
      % (total_hits, len(rs), 100 * total_hits / len(rs)))
print("目标：把这几个数字压到 5% 以下，并持续下降")

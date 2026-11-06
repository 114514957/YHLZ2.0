# -*- coding: utf-8 -*-
"""查清楚：身份样本到底有没有、覆盖什么；v9t6/v9t7 在 g18 上的原始回答各是什么。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
D = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")

rows = []
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    with io.open(os.path.join(D, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

ident = [r for r in rows if str(r.get("source", "")).startswith("identity")]
print("identity 样本：%d 条" % len(ident))

qs = Counter()
for r in ident:
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    qs[q.strip()[:24]] += 1
print("问题种类 %d 种，Top12：" % len(qs))
for q, c in qs.most_common(12):
    print("   %-26s ×%d" % (q, c))

print("\n抽 6 条：")
for r in ident[:6]:
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    print("   Q: %s" % q[:40])
    print("   A: %s" % a[:70])

print("\n=== g18 各版本原始回答 ===")
for pat in ("*group_v9t6_group_cpu.json", "*group_v9t7_group.json"):
    hits = sorted(glob.glob(os.path.join(RUNS, pat)))
    if not hits:
        continue
    d = json.load(io.open(hits[-1], encoding="utf-8"))
    g18 = next((x for x in d["results"] if x["id"] == "g18"), None)
    print("  %-22s %r" % (d.get("tag"), (g18 or {}).get("answer", "")[:80]))

print("\n=== p01（私聊口径·你是什么）各版本 ===")
for pat in ("*persona56_flow_cold.json", "*persona56_v9t7_56.json"):
    hits = sorted(glob.glob(os.path.join(RUNS, pat)))
    if not hits:
        continue
    d = json.load(io.open(hits[-1], encoding="utf-8"))
    p01 = next((x for x in d["results"] if x["id"] == "p01"), None)
    print("  %-22s %s %r" % (d.get("tag"), p01.get("ok"), (p01.get("answer") or "")[:70]))

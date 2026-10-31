#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""素材统计与达标判定（老爹「先统计素材，是否够，是否达标」）。

分三层：
  ① PT（continued pretraining）：篇数 / token / 池配比 / 每篇密度 / token-per-param
  ② SFT：名义条数 vs 四门通过 vs 已签正式集（**能训的到底是哪个数**）
  ③ 判定：够不够、达不达标、缺口在哪
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PARAMS = 5.48e9          # gemma-4-e4b 实测总参数量
TARGET_DOCS = 80000

print("=" * 78)
print("一、PT（continued pretraining）")
print("=" * 78)
man = json.load(io.open("data/pt/manifest.json", encoding="utf-8"))
tot_d, tot_t, tot_c = man["total_docs"], man["total_tokens"], man["total_chars"]
pools, budget = man["pools"], man["pool_budget"]
print("总篇数 %s ｜总 token %s ｜总字符 %s" % (
    format(tot_d, ","), format(tot_t, ","), format(tot_c, ",")))
print("相对 8 万目标：**%.2f%%**" % (100.0 * tot_d / TARGET_DOCS))
print("相对模型规模：**%.4f token/参数**（5.48B 参数）" % (tot_t / PARAMS))
print()
print("%-18s %9s %9s %9s %9s %9s" % (
    "池", "篇数", "篇数占比", "篇数达标", "token", "token占比"))
print("-" * 78)
for k in ("self_core", "speaking_general", "tools_concept", "context"):
    p = pools[k]
    print("%-18s %9s %8.1f%% %8.1f%% %9s %8.1f%%" % (
        k, format(p["docs"], ","), 100.0 * p["docs"] / tot_d,
        100.0 * p["docs"] / budget[k], format(p["tokens"], ","),
        100.0 * p["tokens"] / tot_t))
print("-" * 78)
print("%-18s %9s %8.1f%% %8s %9s %8.1f%%" % (
    "合计", format(tot_d, ","), 100.0, "35.8%", format(tot_t, ","), 100.0))

print("\n每篇平均字符（看密度差异）：")
for k in ("self_core", "speaking_general", "tools_concept", "context"):
    p = pools[k]
    print("  %-18s %6.0f 字符/篇 ｜%5.0f token/篇"
          % (k, p["chars"] / p["docs"], p["tokens"] / p["docs"]))

print("\n缺口（按篇数）：")
for k in ("self_core", "speaking_general", "tools_concept", "context"):
    p = pools[k]
    gap = budget[k] - p["docs"]
    print("  %-18s 还差 %6s 篇" % (k, format(gap, ",")))

print("\n" + "=" * 78)
print("二、SFT（v9y 口径）")
print("=" * 78)
tot = Counter()
for sp in ("train", "val", "test"):
    p = "data/finetune/sft_persona_v9y_%s.jsonl" % sp
    if os.path.exists(p):
        tot[sp] = sum(1 for x in io.open(p, encoding="utf-8") if x.strip())
print("全量：train %s / val %s / test %s ｜合计 %s" % (
    format(tot["train"], ","), tot["val"], tot["test"], format(sum(tot.values()), ",")))

for prefix, label in (("sft_persona_v9y_gated", "四门通过（正式集）"),):
    s = 0
    parts = []
    for sp in ("train", "val", "test"):
        p = "data/finetune/%s_%s.jsonl" % (prefix, sp)
        if os.path.exists(p):
            n = sum(1 for x in io.open(p, encoding="utf-8") if x.strip())
            parts.append("%s %s" % (sp, n))
            s += n
    print("%s：%s ｜合计 **%s**" % (label, " / ".join(parts), s))
print("未签隔离：%s 条（名义量 − 四门通过）" % format(sum(tot.values()) - s, ","))

# SFT token
import re  # noqa: E402
def approx_tokens(text):
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - zh
    return int(zh * 1.0 + other * 0.3)

for tag, prefix in (("全量", "sft_persona_v9y"), ("正式集", "sft_persona_v9y_gated")):
    tk = 0
    n = 0
    for sp in ("train", "val", "test"):
        p = "data/finetune/%s_%s.jsonl" % (prefix, sp)
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            n += 1
            tk += approx_tokens("".join(m.get("content") or ""
                                        for m in r["messages"]))
    print("  %-6s %5d 条 ｜约 %s token" % (tag, n, format(tk, ",")))

print("\n" + "=" * 78)
print("三、判定")
print("=" * 78)

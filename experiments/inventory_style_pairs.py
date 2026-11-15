# -*- coding: utf-8 -*-
"""盘点所有带 answer 的评测记录，看能凑出多少「同题不同风格」的对照。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DIRS = [os.path.join(YH, "llm_workbench", "data", "runs"),
        os.path.join(YH, "experiments", "runs")]

BAD_WA = re.compile(r"^(哇|哇哦|哇塞|哇哈|哎呦|嘿)")
BAD_Q = re.compile(r"[？?]\s*$")
SVC = re.compile(r"(您好|请问有什么|可以帮您|希望.{0,4}帮助|作为一个|AI ?助手)")

by_q = defaultdict(list)
files = 0
for d in DIRS:
    for p in glob.glob(os.path.join(d, "*.json")):
        try:
            data = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        files += 1
        rows = []
        if isinstance(data, dict):
            if "results" in data:
                rows = data["results"]
            elif "repeats" in data:
                for r in data["repeats"]:
                    rows += (r.get("results") or [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            q = r.get("q") or r.get("question")
            a = r.get("answer") or r.get("a")
            if q and a:
                by_q[q.strip()].append({"a": a.strip(), "src": os.path.basename(p)})

multi = {q: v for q, v in by_q.items() if len(v) >= 2}
print("扫描 %d 个记录文件｜题目 %d 个｜有 ≥2 条不同回答的题 %d 个"
      % (files, len(by_q), len(multi)))

# 统计风格标签
stat = Counter()
for q, vs in multi.items():
    for v in vs:
        t = []
        if BAD_WA.match(v["a"]):
            t.append("哇开头")
        if BAD_Q.search(v["a"]):
            t.append("反问收尾")
        if SVC.search(v["a"]):
            t.append("客服腔")
        if len(v["a"]) < 12:
            t.append("过短")
        for x in t:
            stat[x] += 1
print("\n多答题的风格分布：%s" % dict(stat))

# 能组成对照的：同题里既有坏答案又有好答案
pairs = 0
examples = []
for q, vs in multi.items():
    bad = [v for v in vs if BAD_WA.match(v["a"]) or BAD_Q.search(v["a"]) or SVC.search(v["a"])]
    good = [v for v in vs if not (BAD_WA.match(v["a"]) or BAD_Q.search(v["a"]) or SVC.search(v["a"]))
            and 10 <= len(v["a"]) <= 200]
    if bad and good:
        pairs += 1
        if len(examples) < 5:
            examples.append((q, good[0]["a"], bad[0]["a"]))

print("\n可组 DPO 对照的题目：**%d** 个" % pairs)
for q, g, b in examples:
    print("\n  问：%s" % q[:40])
    print("  好：%s" % g[:70])
    print("  坏：%s" % b[:70])

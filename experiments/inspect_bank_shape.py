# -*- coding: utf-8 -*-
"""摸清题库结构：类别分布、字段用法、max_len 惯例、闸门题。"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))

import group_bank as GB  # noqa: E402
import persona_bank as PB  # noqa: E402

print("persona 题数 %d｜类别 %s｜GATE %s｜JUDGE_VERSION %s"
      % (len(PB.PERSONA_BANK), PB.CATEGORIES, PB.GATE_IDS, PB.JUDGE_VERSION))
cat = Counter(e.get("cat") for e in PB.PERSONA_BANK)
print("  类别分布：%s" % dict(cat))
fields = Counter()
for e in PB.PERSONA_BANK:
    for k in e:
        fields[k] += 1
print("  字段使用次数：%s" % dict(fields))
ml = [e.get("max_len") for e in PB.PERSONA_BANK if e.get("max_len")]
print("  max_len：%d 题有｜min %d｜max %d｜常见 %s"
      % (len(ml), min(ml), max(ml), Counter(ml).most_common(4)))
print("  no_tail_question：%d 题" % sum(1 for e in PB.PERSONA_BANK if e.get("no_tail_question")))
print("  expect_any_tool：%d 题｜forbid_tools：%d 题"
      % (sum(1 for e in PB.PERSONA_BANK if e.get("expect_any_tool")),
         sum(1 for e in PB.PERSONA_BANK if e.get("forbid_tools"))))

print("\n--- 每类抽 2 题看写法 ---")
seen = defaultdict(int)
for e in PB.PERSONA_BANK:
    c = e.get("cat")
    if seen[c] >= 2:
        continue
    seen[c] += 1
    print("\n[%s] %s｜%s" % (c, e.get("id"), e.get("q")))
    for k in ("all_keys", "keys", "negative", "max_len", "no_tail_question",
              "expect_any_tool", "forbid_tools", "依据"):
        if e.get(k) is not None:
            v = e[k]
            print("    %-16s %s" % (k, str(v)[:90]))

print("\n=== group：%d 题｜字段 %s ===" % (len(GB.GROUP_BANK),
      dict(Counter(k for e in GB.GROUP_BANK for k in e))))
for e in GB.GROUP_BANK[:2]:
    print("\n[%s] scene=%s gate=%s" % (e.get("id"), str(e.get("scene"))[:40], e.get("gate")))
    for m in e.get("messages") or []:
        print("    %s: %s" % (m.get("role"), str(m.get("content"))[:60]))
    print("    keys=%s max_len=%s no_tail=%s"
          % (e.get("keys"), e.get("max_len"), e.get("no_tail_question")))

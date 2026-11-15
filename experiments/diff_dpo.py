# -*- coding: utf-8 -*-
"""对比 v9t10 与 v9t10-dpo 的失败项，看 DPO 治好了什么、弄坏了什么。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"
WB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"


def load_suite(path, suite):
    d = json.load(io.open(path, encoding="utf-8"))
    rows = d.get("results")
    if rows is None:
        rows = []
        for r in d.get("repeats") or []:
            rows += (r.get("results") or [])
    for r in rows:
        if r.get("suite") == suite:
            return set(r.get("failed_ids") or []), r
    return set(), {}


dpo = sorted(glob.glob(os.path.join(RUNS, "*v9t10-dpo.json")))[-1]
base56 = sorted(glob.glob(os.path.join(WB, "*persona56_v9t10_56.json")))[-1]
base_g = sorted(glob.glob(os.path.join(WB, "*group_v9t10_group.json")))[-1]

for suite, bp in (("persona56", base56), ("group", base_g)):
    b, rb = load_suite(bp, suite)
    n, rn = load_suite(dpo, suite)
    print("== %s ==" % suite)
    print("  v9t10     %s/%s｜闸门 %s｜失败 %s"
          % (rb.get("ok"), rb.get("total"), rb.get("gate_ok"), ",".join(sorted(b))))
    print("  v9t10-dpo %s/%s｜闸门 %s｜失败 %s"
          % (rn.get("ok"), rn.get("total"), rn.get("gate_ok"), ",".join(sorted(n))))
    print("  ✅ 修好：%s" % (",".join(sorted(b - n)) or "-"))
    print("  ❌ 新挂：%s" % (",".join(sorted(n - b)) or "-"))
    print()

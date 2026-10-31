#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""缩 cot/cotdeep（老爹 2026-10-22：「缩」）。

背景：cot 600 + cotdeep 780 = **1,380 条算术/计算题**，占 SFT 18.9%。
内容举例：「一盒 70 支，8 盒就是 70×8=560；用掉 40，560-40=520。」
——这不是她的工作流（她的 40 个工具里没有计算器），喂这么多只会稀释风格。

**不搞均匀砍，按对「她的工作」的实际价值分三档**：
  高价值（对她的活有间接用）：
    · multihop  多跳推理   —— 查证要串好几步
    · finderr   找错       —— 核对数据/代码
    · selfcheck 自检       —— 结果对不对要自己验
    · schedule  日程推理   —— 她有 schedule_plan
    · table     表格理解   —— 工具返回常是表格
  中价值：logic 逻辑 / switch 切换 / drill 演练
  低价值：arith 心算 / shop 购物计算  ← 模型本身就会，留几条意思一下

用法：
    python tools/v9_trim_cot.py --dry-run
    python tools/v9_trim_cot.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = "data/finetune/generated_extra_v9y.jsonl"
OUT = "data/finetune/generated_extra_v9y_trimmed.jsonl"

# 每类保留条数
KEEP = {
    "cot:multihop": 28, "cot:finderr": 28, "cotdeep:selfcheck": 28,
    "cotdeep:schedule": 28, "cotdeep:table": 28,
    "cot:logic": 15, "cotdeep:switch": 15, "cotdeep:drill": 15,
    "cot:arith": 8, "cotdeep:shop": 8,
}


def stable_key(r: dict) -> str:
    """按内容哈希排序——可复现，不会每次抽到不同的。"""
    txt = "".join(str(m.get("content") or "") for m in r["messages"])
    return hashlib.sha256(re.sub(r"\s+", "", txt).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = [json.loads(x) for x in io.open(SRC, encoding="utf-8") if x.strip()]
    by_type: dict[str, list] = {}
    other = []
    for r in rows:
        s = str(r.get("source", ""))
        d = s.split(":")[0]
        if d in ("cot", "cotdeep"):
            by_type.setdefault(s, []).append(r)
        else:
            other.append(r)

    print("原：cot/cotdeep %d 条｜其他 %d 条" % (sum(len(v) for v in by_type.values()),
                                              len(other)))
    kept_cot = []
    print("\n%-24s %5s → %4s" % ("题型", "原", "留"))
    for t, items in sorted(by_type.items()):
        want = KEEP.get(t, 12)
        pick = sorted(items, key=stable_key)[:want]
        kept_cot.extend(pick)
        print("  %-22s %5d → %4d" % (t, len(items), len(pick)))
    print("  %-22s %5d → %4d" % ("合计", sum(len(v) for v in by_type.values()),
                                 len(kept_cot)))

    if a.dry_run:
        print("\n保留样例：")
        for r in kept_cot[:3]:
            ans = [m["content"] for m in r["messages"] if m["role"] == "assistant"]
            print("  [%s] %s" % (r["source"], (ans[0] if ans else "")[:80]))
        return 0

    out = kept_cot + other
    with io.open(OUT, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n写出 %d 条 → %s" % (len(out), OUT))
    c = Counter(str(r.get("source", "?")).split(":")[0] for r in out)
    print("维度：%s" % dict(c.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

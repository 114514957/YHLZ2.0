#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""压缩 PT 开源对话里 LCCC 的占比（老爹 2026-10-22：「那些对话最主要的作用是教说话，注意位置」→「接受」A 方案）。

问题：PT 的 speaking_general 里 **LCCC 别人的对话占 53.6%**，压过了 QQ 实录（她自己的）29.2%。
      语言底色不该由微博网友主导。

做法：把 LCCC 压到 speaking 总量 **≤30%**，其余来源（QQ 实录/小说对白/访谈）不动。
      **按质量择优保留，不是随机砍**：
        · 多轮优先（4 回合 > 2 回合）——教说话的价值在多轮互动
        · 长度适中（40–200 字符）
        · 有态度词（否定/反问/感嘆）

用法：
    python tools/v9_trim_lccc_pt.py --ratio 0.30 --dry-run
    python tools/v9_trim_lccc_pt.py --ratio 0.30
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGET = os.path.join(ROOT, "data", "pd", "v9_open_dialogue.jsonl")
ATTITUDE = re.compile(r"不是|才不|谁|凭什么|怎么|干嘛|别|少来|不服|笑话|我就|偏|倒|"
                      r"哼|呸|滚|有趣|有意思|离谱|夸张")


def score(rec: dict) -> float:
    t = rec.get("text") or ""
    turns = t.count("\n") + 1
    ln = len(t)
    s = min(turns, 5) * 2.0
    s += 2.0 if 40 <= ln <= 200 else (1.0 if 30 <= ln < 40 or 200 < ln <= 300 else 0.0)
    s += min(len(ATTITUDE.findall(t)), 3) * 1.0
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = [json.loads(x) for x in io.open(TARGET, encoding="utf-8") if x.strip()]
    lccc = [r for r in rows if "lccc" in str(r.get("source") or "")]
    other = [r for r in rows if "lccc" not in str(r.get("source") or "")]
    print("现有：LCCC %d 篇｜其他开源对话 %d 篇｜合计 %d"
          % (len(lccc), len(other), len(rows)))

    # 目标：LCCC ≤ ratio × (LCCC + 其他 + 其他池外的 speaking)
    # speaking_general 总量 ≈ 这里 open 对话 + 其他来源（QQ/小说对白等）
    # 用当前 speaking 总量估算：open 对话占其中一部分
    import json as _j
    man = _j.load(io.open("data/pt/manifest.json", encoding="utf-8"))
    sp_total = man["pools"]["speaking_general"]["docs"]
    non_open = sp_total - len(rows)          # speaking 里非 open 对话的部分
    # 解 L / (L + non_open + len(other)) <= ratio
    capacity = int((a.ratio / (1 - a.ratio)) * (non_open + len(other)))
    keep_n = max(1, min(capacity, len(lccc)))
    print("speaking 总量 %d（其中非开源对话 %d）" % (sp_total, non_open))
    print("按 ratio=%.2f 计算，LCCC 最多保留 %d 篇（现 %d，将砍 %d）"
          % (a.ratio, keep_n, len(lccc), len(lccc) - keep_n))

    ranked = sorted(lccc, key=lambda r: (-score(r),
                                         -((r.get("text") or "").count("\n"))))
    keep = ranked[:keep_n]
    kept_ratio = len(keep) / max(1, len(keep) + non_open + len(other))
    print("保留后 LCCC 占 speaking 约 %.1f%%" % (100.0 * kept_ratio))
    if keep:
        ls = sorted(len(r.get("text") or "") for r in keep)
        print("保留篇长度：中位 %d｜p90 %d"
              % (ls[len(ls) // 2], ls[int(len(ls) * 0.9)]))

    if a.dry_run:
        print("\n保留样例（前 3）：")
        for r in keep[:3]:
            print("  " + (r.get("text") or "").replace("\n", " ｜ ")[:100])
        return 0

    bak = TARGET.replace(".jsonl", "_压lccc前_20261022.jsonl")
    shutil.copy2(TARGET, bak)
    with io.open(TARGET, "w", encoding="utf-8") as fh:
        for r in keep + other:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n已写回（LCCC %d + 其他 %d = %d 篇）｜备份 %s"
          % (len(keep), len(other), len(keep) + len(other), os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

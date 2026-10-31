#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把个性样本按类别均衡压到目标数量（老爹 2026-10-21：「压」）。

为什么压：personality 已占 SFT 31.2%、权重 1.0 占 38.5%，会让她"很会表态、不太会干活"。

压法（**不是随机砍**）：
  · **按 category 均衡**：每类保留相同数量，避免某类被砍光；
  · 同类内按内容哈希稳定抽样（可复现），不按生成顺序（避免总是留前几条）。

用法：
    python tools/v9_trim_personality.py --keep 1200 --dry-run
    python tools/v9_trim_personality.py --keep 1200
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

P = "docs/素材/个性样本.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=1200)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = io.open(P, encoding="utf-8").read()
    m = re.search(r"(?ms)^(.*?)(?=^## )", text)
    head = m.group(1) if m else ""
    raw = re.split(r"(?m)^##\s+", text)[1:]
    print("现有 %d 块｜目标 %d 块" % (len(raw), a.keep))

    by_cat: dict[str, list] = defaultdict(list)
    for b in raw:
        cat = ""
        for ln in b.split("\n"):
            s = ln.strip()
            if s.startswith("- category:"):
                cat = s.split(":", 1)[1].strip()
                break
        by_cat[cat or "未分类"].append(b)

    cats = sorted(by_cat)
    per = a.keep // max(1, len(cats))
    print("类别 %d 个，每类配额约 %d 条" % (len(cats), per))

    keep_blks, stat = [], Counter()
    for cat in cats:
        items = by_cat[cat]
        # 按内容哈希排序（稳定、可复现），再取前 per 条
        items_sorted = sorted(
            items, key=lambda b: hashlib.sha256(
                re.sub(r"\s+", "", b).encode("utf-8")).hexdigest())
        take = items_sorted[:per]
        keep_blks.extend(take)
        stat[cat] = len(take)
        print("  %-10s %4d → %4d" % (cat, len(items), len(take)))

    # 按原顺序重排（保持文件里类别交错，不扎堆）
    order = {re.sub(r"\s+", "", b): i for i, b in enumerate(raw)}
    keep_blks.sort(key=lambda b: order.get(re.sub(r"\s+", "", b), 99999))

    # 重编号
    out = []
    for i, b in enumerate(keep_blks, 1):
        lines = b.split("\n")
        head_line = lines[0].strip()
        label = head_line.split("｜", 1)[1] if "｜" in head_line else "个性"
        lines[0] = "性-t%04d｜%s" % (i, label)
        out.append("## " + "\n".join(lines).rstrip() + "\n")

    ok = 0
    for b in out:
        if G.check_block("x", b, "general")["status"] != "FAIL":
            ok += 1
    print("\n保留 %d 块（门禁通过 %d）｜剔除 %d（%.1f%%）"
          % (len(out), ok, len(raw) - len(out),
             100.0 * (len(raw) - len(out)) / len(raw)))

    if a.dry_run:
        print("（dry-run，未写盘）")
        return 0

    bak = P.replace(".md", "_压缩前.md")
    shutil.copy2(P, bak)
    new_head = head.replace(
        "# 元亨个性样本（2040 块）",
        "# 元亨个性样本（%d 块·按类均衡压缩）" % len(out))
    new_head = re.sub(r"（\d+ 块）", "（%d 块·按类均衡压缩）" % len(out), new_head, count=1)
    new_head += ("> 2026-10-21 老爹「压」：从 2,040 压到 %d，"
                 "**按 category 均衡 + 内容哈希稳定抽样**，不是砍尾巴。\n\n" % len(out))
    with io.open(P, "w", encoding="utf-8") as fh:
        fh.write(new_head)
        for b in out:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写回 %s（备份 %s）" % (P, os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

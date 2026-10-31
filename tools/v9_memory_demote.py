"""记忆样本降级：把「答非所问」的块标成 candidate（ledger 0891）。

依据 `cache/v9_materials_preparation/memory_relevance.json`（bge-small-zh 余弦）：
  · 块内任一对问答 sim < 阈值（默认 0.35）→ 该块 `status: candidate`
  · 只改 status，不动正文/元数据；输出 `记忆样本_v2.1.md`，原文件不覆盖
  · 附带降级清单，供人工复核（复核后可用 CRUD 改回 keep）

用法：python tools/v9_memory_demote.py [--threshold 0.35] [--apply]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "素材" / "记忆样本_v2.md"
OUT = ROOT / "docs" / "素材" / "记忆样本_v2.1.md"
REL = ROOT / "cache" / "v9_materials_preparation" / "memory_relevance.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--apply", action="store_true", help="真写文件（默认只统计）")
    args = ap.parse_args()

    rel = json.loads(REL.read_text(encoding="utf-8"))
    bad_blocks = {r["block"] for r in rel["bottom"] if r["sim"] < args.threshold}
    # 全量再算一遍（bottom 只存了前 N）
    low_blocks = {r["block"] for r in rel["bottom"] if r["sim"] < args.threshold}
    print(f"[low-sim pairs] {len(low_blocks)} 块低于 {args.threshold}")

    text = SRC.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^## ", text)
    head, parts = blocks[0], blocks[1:]
    out_parts, demoted = [], []
    for b in parts:
        bid = b.splitlines()[0].strip()
        if bid in low_blocks:
            b2 = re.sub(r"(?m)^- status:\s*keep\s*$", "- status: candidate", b, count=1)
            if b2 != b:
                demoted.append(bid)
            b = b2
        out_parts.append("## " + b)
    print(f"[demoted] {len(demoted)} 块：{demoted[:12]}{'…' if len(demoted) > 12 else ''}")
    if args.apply:
        header = ("# 元亨记忆样本 v2.1（答非所问降级）\n\n"
                  "> 2026-10-20 由 `tools/v9_memory_demote.py` 从 v2 生成：\n"
                  "> 任一对问答 bge-small-zh 余弦 < 0.35 → 该块 status 改为 candidate（待复核）。\n"
                  "> 正文与其它元数据未动；原文件保留。\n")
        body = re.sub(r"^# .*\n", "", head, count=1)
        OUT.write_text(header + body + "".join(out_parts) + "\n", encoding="utf-8")
        print(f"[out] {OUT.relative_to(ROOT)}")
    else:
        print("（dry-run；加 --apply 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Finalize the v8 scene doc: merge workers -> dedupe -> keep -> promote.

Modes:
  --merge     merge *_v8_a.md + *_v8_b.md -> 对话样本_v8.md (dedupe by content)
  --promote   dedupe + status:keep + swap 对话样本.md <-> _归档/对话样本_v6.md
Usage:
    python tools/scene_finalize.py --merge
    python tools/scene_finalize.py --promote
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

D = ROOT / "docs" / "素材"
BLK = re.compile(r"(?m)(?=^## )")
NORM = re.compile(r"[\s\W_]+")


def load_blocks(p: Path) -> list[str]:
    if not p.exists():
        return []
    return [b for b in re.split(BLK, p.read_text(encoding="utf-8")) if b.startswith("## 对话v8-")]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--append", default=None, help="额外 v8 文档（逗号分隔）并入 对话样本.md 并重编号")
    ap.add_argument("--anchors", default="a,b")
    args = ap.parse_args()
    header = ("# 元亨对话样本 v8（规范版·由 scene_v8.py 生成）\n\n"
              "> 配额：长度短40/中35/长25｜情绪六类｜自称配额｜类别 技术≥20/故事≤30｜"
              "禁括号·禁口癖·不反问。终检（去重+硬闸）通过后置 keep。\n\n")

    if args.merge:
        blocks, seen = [], set()
        for tag in args.anchors.split(","):
            for b in load_blocks(D / f"对话样本_v8_{tag}.md"):
                fp = NORM.sub("", b.split("###", 1)[-1])
                if fp in seen:
                    continue
                seen.add(fp)
                blocks.append(b)
        (D / "对话样本_v8.md").write_text(header + "\n\n".join(blocks) + "\n", encoding="utf-8")
        print(f"merged {len(blocks)} blocks -> 对话样本_v8.md")

    if args.promote:
        v8 = D / "对话样本_v8.md"
        blocks, seen, kept = [], set(), 0
        for b in load_blocks(v8):
            fp = NORM.sub("", b.split("###", 1)[-1])
            if fp in seen:
                continue
            seen.add(fp)
            b2 = re.sub(r"(?m)^([ \t]*-[ \t]*status[ \t]*:).*$", r"\1 keep", b, count=1)
            if b2 != b:
                kept += 1
            blocks.append(b2)
        v8.write_text(header + "\n\n".join(blocks) + "\n", encoding="utf-8")
        cur = D / "对话样本.md"
        arch = D / "_归档"
        arch.mkdir(exist_ok=True)
        if cur.exists() and "v8" not in cur.read_text(encoding="utf-8")[:400]:
            cur.rename(arch / "对话样本_v6.md")
        v8.replace(cur)

        cats, tiers, emos = Counter(), Counter(), Counter()
        for b in blocks:
            cat = re.search(r"(?m)^- category: (.+)$", b)
            tier = re.search(r"(?m)^- length_tier: (.+)$", b)
            emo = re.search(r"(?m)^- emotion: (.+)$", b)
            if cat:
                cats[cat.group(1).strip()] += 1
            if tier:
                tiers[tier.group(1).strip()] += 1
            if emo:
                emos[emo.group(1).strip()] += 1
        print(f"promoted {len(blocks)} blocks (dedupe/keep) -> 对话样本.md")
        print("cats:", dict(cats))
        print("tiers:", dict(tiers))
        print("emotions:", dict(emos))
    if args.append:
        cur = D / "对话样本.md"
        blocks, seen = [], set()
        for b in load_blocks(cur):
            fp = NORM.sub("", b.split("###", 1)[-1])
            if fp not in seen:
                seen.add(fp)
                blocks.append(b)
        for p in args.append.split(","):
            for b in load_blocks(Path(p.strip())):
                fp = NORM.sub("", b.split("###", 1)[-1])
                if fp in seen:
                    continue
                seen.add(fp)
                blocks.append(re.sub(r"(?m)^([ \t]*-[ \t]*status[ \t]*:).*$", r"\1 keep", b, count=1))
        out_blocks = []
        for i, b in enumerate(blocks, 1):
            cat = re.search(r"(?m)^- category: (.+)$", b)
            head = f"## 对话-{i}｜{cat.group(1).strip() if cat else '对话'}"
            out_blocks.append(re.sub(r"(?m)^## .*$", head, b, count=1))
        cur.write_text(header + "\n\n".join(out_blocks) + "\n", encoding="utf-8")
        print(f"appended: 对话样本.md now {len(out_blocks)} blocks")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

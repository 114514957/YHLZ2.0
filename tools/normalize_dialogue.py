"""Normalize dialogue-block docs so every round is exactly one 问 and one 答.

Merges consecutive same-kind turns (an extra 答 from another role folds into the
previous 答 with a "角色：..." prefix), re-pairs alternately and renumbers
问K/答K; orphan turns (a 问 without 答, or vice versa) are dropped. Idempotent.

Usage:
    python tools/normalize_dialogue.py                 # dry-run (count)
    python tools/normalize_dialogue.py --write         # apply
    python tools/normalize_dialogue.py --doc <path> --write
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC = ROOT / "docs" / "素材" / "对话样本.md"
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)


def normalize(blk: str) -> tuple[str, bool]:
    ms = list(TURN.finditer(blk))
    if not ms:
        return blk, False
    head = blk[:ms[0].start()]
    turns = []
    for i, m in enumerate(ms):
        role = m.group(1).strip()
        kind = m.group(2)
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        turns.append([role, kind, blk[m.end():end].strip()])

    merged: list[list[str]] = []
    for role, kind, text in turns:
        if merged and merged[-1][1] == kind:
            prev = merged[-1]
            prev[2] = prev[2] + (f"；{role}：{text}" if prev[0] != role else "；" + text)
        else:
            merged.append([role, kind, text])

    pairs, j = [], 0
    while j < len(merged):
        if merged[j][1] == "问":
            a = merged[j + 1] if j + 1 < len(merged) and merged[j + 1][1] == "答" else None
            pairs.append((merged[j], a))
            j += 2 if a else 1
        else:
            pairs.append((None, merged[j]))
            j += 1

    lines, k = [], 0
    for q, a in pairs:
        if not (q and a):
            continue
        k += 1
        lines.append(f"### {q[0]}问{k}\n{q[2]}")
        lines.append(f"### {a[0]}答{k}\n{a[2]}")
    new = head.rstrip() + "\n" + "\n".join(lines) + "\n"
    return new, new.strip() != blk.strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="对话块问答配对归一")
    ap.add_argument("--doc", default=str(DEFAULT_DOC))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc = Path(args.doc)
    parts = re.split(r"(?m)(?=^## )", doc.read_text(encoding="utf-8"))
    out, fixed = [], 0
    for blk in parts:
        if not blk.startswith("## "):
            out.append(blk)
            continue
        nb, changed = normalize(blk)
        fixed += changed
        out.append(nb if changed else blk)
    if args.write:
        doc.write_text("".join(out), encoding="utf-8")
        print(f"fixed blocks: {fixed}")
    else:
        print(f"[dry] would fix blocks: {fixed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

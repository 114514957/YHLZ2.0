"""小说场景描写段抽取（ledger 0906）。

补"非对白"的那一半：小说里大量描写段（环境/动作/心理），现在完全没进语料。
做法：按段落切，丢掉含引号的对白段、过短/过长段，去重后按书封顶。

产出：data/pd/v9_novel_desc.jsonl（source=noveldesc:<书>，license=owner_waiver）
用法：python tools/v9_novel_desc.py --per-book 2500
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOKS = ROOT / "下载物象" / "图书素材"
OUT = ROOT / "data" / "pd" / "v9_novel_desc.jsonl"


def grams(s: str, n: int = 5) -> frozenset:
    t = "".join(s.split())
    return frozenset(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-book", type=int, default=2500)
    ap.add_argument("--min", type=int, default=200)
    ap.add_argument("--max", type=int, default=800)
    args = ap.parse_args()
    rows, seen, seen_g = [], set(), []
    stats = {}
    for book_dir in sorted(BOOKS.glob("*")):
        if not book_dir.is_dir():
            continue
        book = re.sub(r"[0-9a-f]{16}$", "", book_dir.name)
        n = 0
        for f in sorted(book_dir.glob("*.nb")):
            if n >= args.per_book:
                break
            text = f.read_text(encoding="utf-8", errors="replace")
            for para in re.split(r"\n+", text):
                p = para.strip()
                if not (args.min <= len(p) <= args.max):
                    continue
                if "「" in p or "“" in p or "\"" in p:      # 对白段不要
                    continue
                if p.count("。") < 2:                        # 太碎不要
                    continue
                h = hashlib.sha256(p.encode()).hexdigest()[:16]
                if h in seen:
                    continue
                g = grams(p)
                if any(len(g & o) / max(1, len(g | o)) > 0.8 for o in seen_g[-300:]):
                    continue
                seen.add(h)
                seen_g.append(g)
                rows.append({"text": p, "source": f"noveldesc:{book}",
                             "source_id": f"ndesc#{book}#{n}", "group_id": f"noveldesc:{book}",
                             "license": "owner_waiver",
                             "license_note": "老爹 D-3 裁定：仅本地非商用训练，不对外分发",
                             "chars": len(p), "content_hash": h})
                n += 1
                if n >= args.per_book:
                    break
        stats[book] = n
        print(f"  {book}: {n} 段")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    chars = sum(r["chars"] for r in rows)
    print(json.dumps({"rows": len(rows), "chars": chars, "by_book": stats,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

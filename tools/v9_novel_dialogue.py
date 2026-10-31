"""小说对白抽取（ledger 0905）。

老爹问「那么多书里就这点能用的？」——小说 1,898 万字，现在只切了 2,322 个 8k 块（PT 用），
SFT 里几乎没用。本脚本把小说里的**对白**抽出来，做成说话类素材：

  · 抓引号内的话（「」“” ""），丢弃旁白；
  · 连续对白成组（默认 6 句一组），保留说话人线索（xx说/道 前文）；
  · 过滤：中文占比 <60%、单句 <6 字、超过 80 字（太长像独白）都丢；
  · 去重（内容哈希）+ 近重（5-gram Jaccard）。

产出：data/pd/v9_novel_dialogue.jsonl（source=noveldlg:<书>，license=owner_waiver）
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
OUT = ROOT / "data" / "pd" / "v9_novel_dialogue.jsonl"

QUOTE = re.compile(r"[「“\"]([^」”\"]{6,80})[」”\"]")
SPEAKER = re.compile(r"([\u4e00-\u9fa5]{2,4})(?:说|道|问|答|喊|叫|笑|叹)")


def cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    c = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return c / len(s)


def grams(s: str, n: int = 5) -> frozenset:
    t = "".join(s.split())
    return frozenset(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", type=int, default=6)
    ap.add_argument("--per-book", type=int, default=4000)
    args = ap.parse_args()
    rows, seen, seen_grams = [], set(), []
    stats = {}
    for book_dir in sorted(BOOKS.glob("*")):
        if not book_dir.is_dir():
            continue
        book = re.sub(r"[0-9a-f]{16}$", "", book_dir.name)
        quotes, n = [], 0
        for f in sorted(book_dir.glob("*.nb")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in QUOTE.finditer(text):
                q = re.sub(r"\s+", "", m.group(1))
                if len(q) < 6 or len(q) > 80 or cjk_ratio(q) < 0.6:
                    continue
                pre = text[max(0, m.start() - 24):m.start()]
                sp = SPEAKER.search(pre)
                quotes.append({"who": sp.group(1) if sp else "", "say": q})
            if len(quotes) >= args.per_book * 2:
                break
        # 成组
        for i in range(0, len(quotes) - args.group, args.group):
            grp = quotes[i:i + args.group]
            body = "\n".join(f"{g['who'] or '某'}：{g['say']}" for g in grp)
            h = hashlib.sha256(body.encode()).hexdigest()[:16]
            if h in seen:
                continue
            g = grams(body)
            if any(len(g & o) / max(1, len(g | o)) > 0.8 for o in seen_grams[-400:]):
                continue
            seen.add(h)
            seen_grams.append(g)
            rows.append({"text": body, "source": f"noveldlg:{book}",
                         "source_id": f"ndlg#{book}#{n}", "group_id": f"noveldlg:{book}",
                         "license": "owner_waiver",
                         "license_note": "老爹 D-3 裁定：仅本地非商用训练，不对外分发",
                         "chars": len(body), "content_hash": h})
            n += 1
            if n >= args.per_book:
                break
        stats[book] = n
        print(f"  {book}: {n} 组 / 引号 {len(quotes)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "by_book": stats,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

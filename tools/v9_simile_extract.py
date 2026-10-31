"""比喻/比方抽取（ledger 0907）。

老爹：「还有有趣的比方」。
从小说、教材、公版文本里抓**比喻句**（像/好像/如同/好比/仿佛/犹如/似的/一般），
保留完整句，做成"讲道理会打比方"的素材。

筛选：句长 30–140 字；含比喻标记；中文占比 ≥70%；去重 + 近重。
产出：data/pd/v9_similes.jsonl（source=simile:<来源>）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd" / "v9_similes.jsonl"
BOOKS = ROOT / "下载物象" / "图书素材"
MARK = re.compile(r"像[^，。]{1,20}(一样|似的|那样|一般)|如同[^，。]{2,20}|好比[^，。]{2,20}|"
                  r"犹如[^，。]{2,20}|宛如[^，。]{2,20}|活像[^，。]{1,12}|像极了")
SENT = re.compile(r"[^。！？!?\n]{12,160}[。！？!?]")


def cjk_ratio(s: str) -> float:
    return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff") / max(1, len(s))


def grams(s: str, n: int = 5) -> frozenset:
    t = "".join(s.split())
    return frozenset(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


def texts():
    for d in sorted(BOOKS.glob("*")):
        if not d.is_dir():
            continue
        book = re.sub(r"[0-9a-f]{16}$", "", d.name)
        for f in sorted(d.glob("*.nb"))[:200]:
            yield f"novel:{book}", f.read_text(encoding="utf-8", errors="replace")
    for p, src in ((ROOT / "data/pd/v9_refbooks.jsonl", "refbook"),
                   (ROOT / "data/pd/v9_knowledge.jsonl", "know"),
                   (ROOT / "data/pd/v9_pd.jsonl", "pd")):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    d = json.loads(line)
                    yield f"{src}:{d.get('source', '')}", d.get("text") or ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-source", type=int, default=800)
    args = ap.parse_args()
    rows, seen, seen_g, count = [], set(), [], {}
    for src, text in texts():
        n = count.get(src, 0)
        if n >= args.per_source:
            continue
        for m in SENT.finditer(text):
            s = m.group(0).strip()
            if not MARK.search(s) or cjk_ratio(s) < 0.7 or len(s) < 30:
                continue
            if re.search(r"仿佛(还|正|要|在)|好像(还|正|要|在)", s):
                continue
            h = hashlib.sha256(s.encode()).hexdigest()[:16]
            if h in seen:
                continue
            g = grams(s)
            if any(len(g & o) / max(1, len(g | o)) > 0.8 for o in seen_g[-200:]):
                continue
            seen.add(h)
            seen_g.append(g)
            rows.append({"text": s, "source": f"simile:{src}", "license": "cc-by-sa-4.0",
                         "chars": len(s), "content_hash": h})
            n += 1
            count[src] = n
            if n >= args.per_source:
                break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "by_source": dict(sorted(count.items(),
                                                                 key=lambda kv: -kv[1])[:10]),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    for r in rows[:5]:
        print("  ·", r["text"][:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

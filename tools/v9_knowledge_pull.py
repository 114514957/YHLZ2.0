"""按主题拉教材/科普（ledger 0907）。

老爹：「逻辑图书，有趣的科普书」。
随机抽页抽不到教材——改成**按主题搜索**（MediaWiki `list=search`）再逐页取正文：
  逻辑 / 谬误 / 推理 / 数学 / 物理 / 宇宙 / 生物 / 科普 / 比喻
来源：zh.wikibooks（教材）、zh.wikipedia（百科/科普）、zh.wikiversity（课程）。

产出：data/pd/v9_knowledge.jsonl（source=know:<site>:<query>，license=cc-by-sa-4.0）
用法：python tools/v9_knowledge_pull.py --per-query 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd" / "v9_knowledge.jsonl"
PROXY = "http://127.0.0.1:7897"

SITES = {
    "wikibooks": "https://zh.wikibooks.org/w/api.php",
    "wikipedia": "https://zh.wikipedia.org/w/api.php",
}
QUERIES = ["逻辑", "谬误", "推理", "数学", "物理", "宇宙", "生物", "科普", "比喻"]


def opner():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(base: str, params: dict, timeout: int = 60) -> dict:
    qs = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{base}?{qs}",
                                 headers={"User-Agent": "YHLZ-know/1.0 (local training)"})
    for attempt in range(3):
        try:
            return json.loads(opner().open(req, timeout=timeout).read())
        except Exception:
            time.sleep(3 + attempt * 3)
    raise RuntimeError("api failed")


def search_titles(base: str, query: str, limit: int) -> list[str]:
    d = api(base, {"action": "query", "list": "search", "srsearch": query,
                   "srlimit": min(50, limit), "srnamespace": 0})
    return [x["title"] for x in ((d.get("query") or {}).get("search") or [])]


def extract(base: str, title: str) -> str:
    d = api(base, {"action": "query", "titles": title, "prop": "extracts",
                   "explaintext": 1, "redirects": 1})
    pages = list(((d.get("query") or {}).get("pages") or {}).values())
    return (pages[0].get("extract") or "").strip() if pages else ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=12)
    ap.add_argument("--chunk", type=int, default=6000)
    args = ap.parse_args()
    rows, stats, seen = [], {}, set()
    for site, base in SITES.items():
        for q in QUERIES:
            n = 0
            try:
                titles = search_titles(base, q, args.per_query * 2)
            except Exception as exc:  # noqa: BLE001
                print(f"[{site}:{q}] search fail {type(exc).__name__}", file=sys.stderr)
                continue
            for title in titles:
                if n >= args.per_query:
                    break
                if f"{site}:{title}" in seen:
                    continue
                try:
                    text = extract(base, title)
                except Exception:
                    continue
                seen.add(f"{site}:{title}")
                cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
                if len(text) < 400 or cjk < len(text) * 0.4:
                    continue
                # 相关性：标题含主题词，或正文里主题词出现 >=3 次（过滤搜索噪音）
                if q not in title and text.count(q) < 3:
                    continue
                for i in range(0, len(text), args.chunk):
                    seg = text[i:i + args.chunk]
                    if len(seg) < 500:
                        continue
                    rows.append({"text": seg, "source": f"know:{site}:{q}",
                                 "title": title, "license": "cc-by-sa-4.0",
                                 "source_url": f"https://{site}.org/wiki/" +
                                               urllib.parse.quote(title.replace(" ", "_")),
                                 "chars": len(seg),
                                 "content_hash": hashlib.sha256(seg.encode()).hexdigest()[:16]})
                n += 1
                time.sleep(0.6)
            stats[f"{site}:{q}"] = n
            print(f"  {site}:{q} → {n} 页", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "chars": sum(r["chars"] for r in rows),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

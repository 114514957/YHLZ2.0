"""教材 / 工具书拉取（ledger 0905）。

老爹：「还有教材书，工具书」。本机 `下载物象/图书素材` 只有 4 本小说，没有教材/工具书，
所以走**开放许可**的三类源（都是 CC BY-SA，明确可商用/可改写，需署名）：

  · zh.wikibooks   维基教科书 —— 教材（数学/物理/编程/语言…）
  · zh.wiktionary  维基词典 —— 工具书（字词释义、用法）
  · zh.wikipedia   维基百科 —— 百科（概念、定义、综述）

做法：MediaWiki API（`action=query&generator=random` 取页 → `action=parse&prop=wikitext`
取正文 → 去 wiki 标记 → 分块），慢速+重试，全部带 source_url / license / title。

产出：data/pd/v9_refbooks.jsonl（每页一块，license=cc-by-sa-4.0）
用法：python tools/v9_refbooks_pull.py --per-source 30 --chunk 6000
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd" / "v9_refbooks.jsonl"
PROXY = "http://127.0.0.1:7897"

SOURCES = {
    "wikibooks": "https://zh.wikibooks.org/w/api.php",
    "wiktionary": "https://zh.wiktionary.org/w/api.php",
    "wikipedia": "https://zh.wikipedia.org/w/api.php",
}


def opner():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(base: str, params: dict, timeout: int = 60) -> dict:
    qs = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{base}?{qs}",
                                 headers={"User-Agent": "YHLZ-refbooks/1.0 (local training)"})
    for attempt in range(3):
        try:
            return json.loads(opner().open(req, timeout=timeout).read())
        except Exception:
            time.sleep(4 + attempt * 4)
    raise RuntimeError("api failed: " + base)


def clean_wikitext(t: str) -> str:
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", t)
    t = re.sub(r"'''?", "", t)
    t = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", t, flags=re.M)
    t = re.sub(r"^[*#:;]+\s*", "", t, flags=re.M)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fetch_pages(base: str, n: int, min_len: int = 300) -> list[dict]:
    """多批随机取标题 + 逐页取纯文本，直到凑够 n 页。"""
    out, tried, seen = [], 0, set()
    for _batch in range(6):
        if len(out) >= n:
            break
        try:
            data = api(base, {"action": "query", "generator": "random",
                              "grnnamespace": 0, "grnlimit": 50})
        except Exception:
            break
        titles = [(p.get("title") or "").strip()
                  for p in ((data.get("query") or {}).get("pages") or {}).values()]
        new_titles = [x for x in titles if x and x not in seen]
        if not new_titles:
            continue
        seen.update(new_titles)
        for title in new_titles:
            if len(out) >= n:
                break
            tried += 1
            try:
                d = api(base, {"action": "query", "titles": title,
                               "prop": "extracts", "explaintext": 1, "redirects": 1})
                pages = list(((d.get("query") or {}).get("pages") or {}).values())
                text = (pages[0].get("extract") or "").strip() if pages else ""
            except Exception:
                text = ""
            if len(text) < min_len:
                continue
            cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
            title_cjk = sum(1 for ch in title if "\u4e00" <= ch <= "\u9fff")
            if cjk < len(text) * 0.3 and title_cjk < 1:
                continue
            out.append({"title": title, "text": text})
            time.sleep(0.6)
    print(f"  tried {tried} → {len(out)} pages", flush=True)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-source", type=int, default=25)
    ap.add_argument("--chunk", type=int, default=6000)
    args = ap.parse_args()
    rows, stats = [], {}
    for name, base in SOURCES.items():
        got = []
        try:
            min_len = 60 if name == "wiktionary" else 300
            pages = fetch_pages(base, args.per_source, min_len)
            for p in pages:
                text = p["text"]
                for i in range(0, len(text), args.chunk):
                    seg = text[i:i + args.chunk]
                    if len(seg) < min_len:
                        continue
                    got.append({"text": seg, "source": f"refbook:{name}",
                                "title": p["title"], "license": "cc-by-sa-4.0",
                                "source_url": f"https://{name}.org/wiki/" +
                                              urllib.parse.quote(p["title"].replace(" ", "_")),
                                "chars": len(seg),
                                "content_hash": __import__("hashlib").sha256(seg.encode()).hexdigest()[:16]})
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        stats[name] = len(got)
        rows += got
        print(f"[{name}] {len(got)} 块")
        time.sleep(2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "by_source": stats,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""维基文库「慢速」补采（应对 429）：传统书名 + 每页间隔 + 指数退避。

只补**散文叙事**（故事书/经典），给「真善美·人格道德」抽取提供语料。
用法：python tools/v9_ws_slow.py [--pages 10] [--sleep 6]
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
OUT = ROOT / "data" / "pd"
PROXY = "http://127.0.0.1:7897"
API = "https://zh.wikisource.org/w/api.php"

# 传统书名（维基文库用繁体）
BOOKS = {
    "紅樓夢": ["紅樓夢/第一回", "紅樓夢/第二回"],
    "三國演義": ["三國演義/第001回", "三國演義/第002回"],
    "西遊記": ["西遊記/第001回", "西遊記/第002回"],
    "水滸傳": ["水滸傳/第001回"],
    "聊齋志異": ["聊齋志異/卷一"],
    "論語": ["論語/學而第一"],
    "孟子": ["孟子/梁惠王上"],
    "莊子": ["莊子/逍遙遊"],
    "史記": ["史記/卷001"],
    "世說新語": ["世說新語/德行"],
}


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(params: dict, tries: int = 4) -> dict:
    params = {**params, "format": "json"}
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            raw = opener().open(
                urllib.request.Request(url, headers={"User-Agent": "yhlz-pd/1.0 (slow)"}),
                timeout=45).read()
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                time.sleep(8 * (i + 1))
                continue
            raise
        except Exception:
            time.sleep(4)
    raise RuntimeError("retries exhausted")


def wikitext(page: str) -> str:
    d = api({"action": "parse", "page": page, "prop": "wikitext",
             "redirects": "1", "formatversion": "2"})
    return str((d.get("parse") or {}).get("wikitext") or "")


def strip(s: str) -> str:
    import re
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"'''?", "", s)
    s = re.sub(r"^=+\s*", "", s, flags=re.M)
    s = re.sub(r"\s*=+$", "", s, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=6.0)
    args = ap.parse_args()
    docs, evid, n = [], [], 0
    for book, pages in BOOKS.items():
        for page in pages:
            if n >= args.pages:
                break
            try:
                raw = wikitext(page)
            except Exception as exc:  # noqa: BLE001
                evid.append({"page": page, "ok": False, "error": f"{type(exc).__name__}"})
                print(f"  ✗ {page} {type(exc).__name__}")
                time.sleep(args.sleep)
                continue
            text = strip(raw)
            if len(text) >= 800:
                docs.append({"text": text, "source": f"wikisource:{book}",
                             "source_id": f"pd:ws:{page}", "license": "public_domain",
                             "group_id": f"pd:ws:{book}", "chars": len(text),
                             "url": f"{API}?action=parse&page={urllib.parse.quote(page)}",
                             "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
                evid.append({"page": page, "ok": True, "bytes": len(raw),
                             "chars": len(text),
                             "sha16": hashlib.sha256(raw.encode()).hexdigest()[:16]})
                print(f"  ✓ {page} {len(text)} 字")
                n += 1
            time.sleep(args.sleep)
        if n >= args.pages:
            break
    path = OUT / "v9_ws_prose.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    rep = {"docs": len(docs), "chars": sum(d["chars"] for d in docs),
           "evidence": evid, "file": str(path.relative_to(ROOT))}
    (OUT / "ws_prose_manifest.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] {len(docs)} 页 / {rep['chars']} 字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

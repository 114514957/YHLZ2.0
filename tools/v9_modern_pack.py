"""现代素材包：游戏台词（维基语录）+ 现代公版白话（维基文库·鲁迅等）。

老爹 2026-10-20 裁定：**游戏台词可用**（个人非商用；正常引用），按"短句引用+出处标注+不整篇搬运"执行。
维基语录/维基文库页面文本为 CC BY-SA，抓取留 URL 与 sha16 证据；游戏原句版权归各厂商，仅本地使用。

产出：
  data/pd/v9_game_quotes.jsonl   {text, game, page, url, license:"owner_waiver", chars}
  data/pd/v9_modern_prose.jsonl  {text, source, page, url, license:"public_domain", chars}
  data/pd/modern_manifest.json

用法：python tools/v9_modern_pack.py [--ws-pages 12] [--sleep 8]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd"
PROXY = "http://127.0.0.1:7897"
WQ = "https://zh.wikiquote.org/w/api.php"
WS = "https://zh.wikisource.org/w/api.php"

GAMES = ["原神", "崩壞：星穹鐵道", "崩壞3", "重返未來：1999",
         "崩坏：星穹铁道", "崩坏3", "重返未来：1999"]
MODERN_BOOKS = ["吶喊", "彷徨", "朝花夕拾", "野草", "故事新編"]


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(base: str, params: dict, tries: int = 4) -> dict:
    params = {**params, "format": "json"}
    url = base + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            raw = opener().open(urllib.request.Request(
                url, headers={"User-Agent": "yhlz-pd/1.0 (slow)"}), timeout=45).read()
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                time.sleep(10 * (i + 1))
                continue
            raise
        except Exception:
            time.sleep(5)
    raise RuntimeError("retries exhausted")


def clean(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"^[=*:#]+\s*", "", s, flags=re.M)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def wikitext(base: str, page: str) -> str:
    d = api(base, {"action": "parse", "page": page, "prop": "wikitext",
                   "redirects": "1", "formatversion": "2"})
    return str((d.get("parse") or {}).get("wikitext") or "")


def subpages(prefix: str, limit: int = 20) -> list[str]:
    try:
        d = api(WS, {"action": "query", "list": "allpages",
                     "apprefix": prefix + "/", "aplimit": limit})
        return [p["title"] for p in d.get("query", {}).get("allpages", [])]
    except Exception:
        return []


def game_quotes(sleep: float) -> tuple[list[dict], list[dict]]:
    rows, evid = [], []
    for game in GAMES:
        try:
            wt = wikitext(WQ, game)
        except Exception as exc:  # noqa: BLE001
            evid.append({"game": game, "ok": False, "error": type(exc).__name__})
            time.sleep(sleep)
            continue
        text = clean(wt)
        lines = [x.strip() for x in text.split("\n") if x.strip()]
        # 只取"短句/台词"：8–120 字，且不是标题/日期
        quotes = [x for x in lines
                  if 8 <= len(x) <= 120 and not re.match(r"^\d{4}", x)
                  and "Category" not in x and "[[" not in x]
        for i, q in enumerate(quotes):
            rows.append({"text": q, "game": game,
                         "source_id": f"game#{game}#{i}", "page": game,
                         "url": WQ + "?action=parse&page=" + urllib.parse.quote(game),
                         "license": "owner_waiver", "chars": len(q),
                         "content_hash": hashlib.sha256(q.encode()).hexdigest()[:16]})
        evid.append({"game": game, "ok": True, "bytes": len(wt), "quotes": len(quotes),
                     "sha16": hashlib.sha256(wt.encode()).hexdigest()[:16]})
        print(f"  ✓ 语录 {game}: {len(quotes)} 条")
        time.sleep(sleep)
    return rows, evid


def modern_prose(max_pages: int, sleep: float) -> tuple[list[dict], list[dict]]:
    rows, evid = [], []
    n = 0
    for book in MODERN_BOOKS:
        pages = subpages(book, 12) or [book]
        for page in pages:
            if n >= max_pages:
                break
            try:
                wt = wikitext(WS, page)
            except Exception as exc:  # noqa: BLE001
                evid.append({"page": page, "ok": False, "error": type(exc).__name__})
                time.sleep(sleep)
                continue
            text = clean(wt)
            if len(text) >= 800:
                rows.append({"text": text, "source": f"modern:{book}", "page": page,
                             "url": WS + "?action=parse&page=" + urllib.parse.quote(page),
                             "license": "public_domain", "chars": len(text),
                             "source_id": f"modern#{page}",
                             "group_id": f"modern:{book}",
                             "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
                evid.append({"page": page, "ok": True, "chars": len(text),
                             "sha16": hashlib.sha256(wt.encode()).hexdigest()[:16]})
                print(f"  ✓ {page} {len(text)} 字")
                n += 1
            time.sleep(sleep)
        if n >= max_pages:
            break
    return rows, evid


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-pages", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=8.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("[甲] 游戏台词（维基语录）")
    g, ge = game_quotes(args.sleep)
    print("[乙] 现代公版白话（维基文库）")
    m, me = modern_prose(args.ws_pages, args.sleep)
    for name, rows in (("v9_game_quotes.jsonl", g), ("v9_modern_prose.jsonl", m)):
        with (OUT / name).open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "game_quotes": {"rows": len(g), "chars": sum(r["chars"] for r in g)},
                "modern_prose": {"rows": len(m), "chars": sum(r["chars"] for r in m)},
                "evidence": ge + me,
                "license_note": "维基语录/文库页面 CC BY-SA；游戏原句版权归厂商，仅本地非商用训练"}
    (OUT / "modern_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("game_quotes", "modern_prose")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

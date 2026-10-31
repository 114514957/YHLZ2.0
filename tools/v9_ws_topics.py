"""Wikisource 指定篇目拉取：剧本/评书底本（ledger 0909）。

老爹要「有趣、活泼」的对话与「书评」：
  · 老舍《茶馆》——话剧剧本，对话体密集（PD：老舍 1966 卒，2016 起公版）
  · 老舍《駱駝祥子》——京味对白（PD）
  · 评书底本（Category:評書）：三俠五義、小五義、大八義、于公案、永慶昇平前傳、薛剛反唐（PD）

做法：action=parse&prop=text 取 HTML → 去标签 → 6k 分块；license=public_domain。
产出：data/pd/v9_ws_topics.jsonl
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
OUT = ROOT / "data" / "pd" / "v9_ws_topics.jsonl"
API = "https://zh.wikisource.org/w/api.php"
PROXY = "http://127.0.0.1:7897"

TEAPOT = ["茶馆", "茶馆/第一幕", "茶馆/第二幕", "茶馆/第三幕"]
CAMEL = ["駱駝祥子"] + [f"駱駝祥子/{i}" for i in range(1, 25)]
PINGSHU = ["三俠五義", "小五義", "大八義", "于公案", "永慶昇平前傳", "薛剛反唐"]


def opner():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(params: dict) -> dict:
    qs = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{API}?{qs}",
                                 headers={"User-Agent": "YHLZ-ws/1.0 (local training)"})
    for attempt in range(3):
        try:
            return json.loads(opner().open(req, timeout=60).read())
        except Exception:
            time.sleep(3 + attempt * 3)
    raise RuntimeError("api failed")


def strip_html(html: str) -> str:
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"</p>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"&#\d+;", " ", html)
    html = re.sub(r"&[a-z]+;", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=6000)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    targets = [("茶馆", t) for t in TEAPOT] + [("骆驼祥子", t) for t in CAMEL] + \
              [("评书", t) for t in PINGSHU]
    rows, stats, done = [], {}, 0
    for topic, title in targets:
        if done >= args.limit:
            break
        try:
            d = api({"action": "parse", "page": title, "prop": "text",
                     "formatversion": 2, "redirects": 1})
            html = ((d.get("parse") or {}).get("text") or "")
            if isinstance(html, dict):
                html = html.get("*") or ""
            text = strip_html(html)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {title} {type(exc).__name__}", file=sys.stderr)
            continue
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if len(text) < 800 or cjk < len(text) * 0.5:
            stats[title] = 0
            continue
        n = 0
        for i in range(0, len(text), args.chunk):
            seg = text[i:i + args.chunk]
            if len(seg) < 800:
                continue
            rows.append({"text": seg, "source": f"ws:{topic}", "title": title,
                         "license": "public_domain",
                         "source_url": "https://zh.wikisource.org/wiki/" +
                                       urllib.parse.quote(title.replace(" ", "_")),
                         "chars": len(seg),
                         "content_hash": hashlib.sha256(seg.encode()).hexdigest()[:16]})
            n += 1
        stats[title] = n
        done += 1
        print(f"  ✓ {title}: {n} 块", flush=True)
        time.sleep(1.0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows),
                      "chars": sum(r["chars"] for r in rows),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

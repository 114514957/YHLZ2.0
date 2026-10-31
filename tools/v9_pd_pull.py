"""公版（public_domain）文本直采 v2（ledger 0856 修订）。

修正 v1 两处：
  甲) chinese-poetry 文件名按 **1000 偏移**（poet.tang.0/1000/2000…），v1 用 0/1/2 只能拿到一个；
  乙) 维基文库多数典籍是**子页面**（《红楼梦/第一回》…），直接 action=raw 主页面只有目录；
      改用 `list=allpages&apprefix=<书>/` 拉子页清单，再逐页 `action=parse&prop=wikitext`。

产出 `data/pd/v9_pd.jsonl` + `manifest.json`（含每条 URL 与 sha16 证据）。
用法：python tools/v9_pd_pull.py [--poetry-files 6] [--pages-per-book 12]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd"
PROXY = "http://127.0.0.1:7897"
GH = "https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/"
WS_API = "https://zh.wikisource.org/w/api.php"

POETRY_SETS = {"tang": "全唐诗/poet.tang.{off}.json",
               "song": "宋词/ci.song.{off}.json"}
BOOKS = ["红楼梦", "三国演义", "西游记", "水浒传", "聊斋志异", "儒林外史",
         "世说新语", "诗经", "论语", "庄子", "孟子", "楚辞", "唐诗三百首",
         "浮生六记", "陶庵梦忆", "朝花夕拾", "呐喊", "彷徨"]


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def get(url: str, timeout: int = 50) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "yhlz-pd/1.0"})
    return opener().open(req, timeout=timeout).read()


def strip_wikitext(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"'''?", "", s)
    s = re.sub(r"^=+\s*", "", s, flags=re.M)
    s = re.sub(r"\s*=+$", "", s, flags=re.M)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def chunk(text: str, size: int = 12000) -> list[str]:
    paras = [p for p in text.split("\n") if p.strip()]
    out, buf, n = [], [], 0
    for p in paras:
        buf.append(p)
        n += len(p)
        if n >= size:
            out.append("\n".join(buf))
            buf, n = [], 0
    if buf:
        out.append("\n".join(buf))
    return [x for x in out if len(x) >= 300]


def pull_poetry(files: int) -> tuple[list[dict], list[dict]]:
    docs, evid = [], []
    for kind, pattern in POETRY_SETS.items():
        ok = 0
        for i in range(files):
            off = i * 1000
            url = GH + urllib.parse.quote(pattern.format(off=off))
            try:
                raw = get(url, timeout=60)
                items = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                evid.append({"source": f"poetry:{kind}:{off}", "ok": False,
                             "error": f"{type(exc).__name__}: {str(exc)[:70]}"})
                break
            if not isinstance(items, list) or not items:
                break
            blob = []
            for it in items:
                title = str(it.get("title") or "")
                author = str(it.get("author") or "")
                paras = it.get("paragraphs") or it.get("content") or []
                body = "\n".join(str(p) for p in paras)
                if body.strip():
                    blob.append(f"{title}　{author}\n{body}")
            text = "\n\n".join(blob)
            for k, seg in enumerate(chunk(text)):
                docs.append({"text": seg, "source": f"poetry:{kind}",
                             "source_id": f"pd:poetry:{kind}:{off}:{k}",
                             "license": "public_domain",
                             "group_id": f"pd:poetry:{kind}:{off}",
                             "chars": len(seg), "url": url})
            evid.append({"source": f"poetry:{kind}:{off}", "ok": True,
                         "bytes": len(raw), "items": len(items),
                         "sha16": hashlib.sha256(raw).hexdigest()[:16], "url": url})
            ok += 1
        print(f"  poetry:{kind} 文件 {ok} 个")
    return docs, evid


def api(params: dict) -> dict:
    url = WS_API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    return json.loads(get(url))


def subpages(book: str, limit: int) -> list[str]:
    try:
        d = api({"action": "query", "list": "allpages",
                 "apprefix": book + "/", "aplimit": limit})
        return [p["title"] for p in d.get("query", {}).get("allpages", [])]
    except Exception:
        return []


def wikitext_of(page: str) -> str:
    try:
        d = api({"action": "parse", "page": page, "prop": "wikitext",
                 "redirects": "1", "formatversion": "2"})
        return str((d.get("parse") or {}).get("wikitext") or "")
    except Exception:
        return ""


def pull_wikisource(pages_per_book: int) -> tuple[list[dict], list[dict]]:
    docs, evid = [], []
    for book in BOOKS:
        pages = subpages(book, pages_per_book)
        if not pages:
            pages = [book]
        got = 0
        for page in pages:
            raw = wikitext_of(page)
            text = strip_wikitext(raw)
            if len(text) < 300:
                continue
            for k, seg in enumerate(chunk(text)):
                docs.append({"text": seg, "source": f"wikisource:{book}",
                             "source_id": f"pd:ws:{page}:{k}",
                             "license": "public_domain",
                             "group_id": f"pd:ws:{book}",
                             "chars": len(seg),
                             "url": WS_API + "?action=parse&page=" + urllib.parse.quote(page)})
            evid.append({"source": f"wikisource:{book}", "page": page, "ok": True,
                         "bytes": len(raw), "segments": len(chunk(text)),
                         "sha16": hashlib.sha256(raw.encode()).hexdigest()[:16]})
            got += 1
        print(f"  ✓ {book}: {got} 页")
    return docs, evid


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--poetry-files", type=int, default=6)
    ap.add_argument("--pages-per-book", type=int, default=10)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("[甲] chinese-poetry")
    d1, e1 = pull_poetry(args.poetry_files)
    print("[乙] 维基文库")
    d2, e2 = pull_wikisource(args.pages_per_book)
    docs = d1 + d2
    for d in docs:
        d["content_hash"] = hashlib.sha256(d["text"].encode()).hexdigest()[:16]
    path = OUT / "v9_pd.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    manifest = {
        "pulled_at": datetime.now().isoformat(timespec="seconds"),
        "proxy": PROXY,
        "license_note": "原文公有领域；维基文库页面文本 CC BY-SA（只取原文并标注来源页）",
        "docs": len(docs), "chars": sum(d["chars"] for d in docs),
        "long_docs_8k": sum(1 for d in docs if d["chars"] >= 8000),
        "max_chars": max((d["chars"] for d in docs), default=0),
        "evidence": e1 + e2,
        "files": {"jsonl": str(path.relative_to(ROOT))},
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for e in manifest["evidence"] if e.get("ok"))
    print(f"[done] docs={manifest['docs']} chars={manifest['chars']} "
          f"long>=8k={manifest['long_docs_8k']} max={manifest['max_chars']} "
          f"evidence_ok={ok}/{len(manifest['evidence'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

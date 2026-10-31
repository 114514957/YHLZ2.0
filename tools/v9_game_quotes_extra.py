"""换源抓台词 v1：BWiki（崩坏3/星穹铁道）+ 萌娘百科（崩坏3/重返未来1999）。

老爹 2026-10-20：「换源，哪有抓哪」。只用公开 MediaWiki API，慢速、留证据；
只保留 8–120 字短句（台词），入库标 owner_waiver（D-3，个人非商用）。
"""
from __future__ import annotations

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

ENDPOINTS = {
    "bwiki_bh3": "https://wiki.biligame.com/bh3/api.php",
    "bwiki_sr": "https://wiki.biligame.com/sr/api.php",
    "moegirl": "https://moegirl.icu/api.php",
}
# 每站要试的页面（标题；找不到就跳过）
TARGETS = {
    "bwiki_bh3": ["崩坏3", "琪亚娜·卡斯兰娜", "雷电芽衣", "布洛妮娅·扎伊切克"],
    "bwiki_sr": ["崩坏：星穹铁道", "流萤", "三月七", "黄泉"],
    "moegirl": ["崩坏3", "崩壞3", "重返未来：1999", "重返未来1999", "维尔汀"],
}


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def api(base: str, params: dict, timeout: int = 30) -> dict:
    params = {**params, "format": "json"}
    url = base + "?" + urllib.parse.urlencode(params)
    raw = opener().open(urllib.request.Request(
        url, headers={"User-Agent": "yhlz-pd/1.0 (slow)"}), timeout=timeout).read()
    return json.loads(raw)


def wikitext(base: str, page: str) -> str:
    d = api(base, {"action": "parse", "page": page, "prop": "wikitext",
                   "redirects": "1", "formatversion": "2"})
    return str((d.get("parse") or {}).get("wikitext") or "")


def clean(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"^[=*:#|!]+\s*", "", s, flags=re.M)
    s = re.sub(r"\{\|.*?\|\}", "", s, flags=re.S)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


QUOTE_MARK = re.compile(r"[“「『\"]|……|——")


def extract(text: str, cap: int = 200) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not (8 <= len(line) <= 120):
            continue
        if re.match(r"^\d{4}", line) or "Category" in line:
            continue
        if QUOTE_MARK.search(line) or "：" in line and len(line) <= 60:
            out.append(line)
        if len(out) >= cap:
            break
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    rows, evid = [], []
    for wiki, pages in TARGETS.items():
        base = ENDPOINTS[wiki]
        for page in pages:
            try:
                wt = wikitext(base, page)
            except Exception as exc:  # noqa: BLE001
                evid.append({"wiki": wiki, "page": page, "ok": False,
                             "error": type(exc).__name__})
                print(f"  ✗ {wiki}:{page} {type(exc).__name__}")
                time.sleep(2)
                continue
            text = clean(wt)
            quotes = extract(text)
            for i, q in enumerate(quotes):
                rows.append({"text": q, "game": wiki, "page": page,
                             "source_id": f"gx#{wiki}#{page}#{i}",
                             "url": base + "?action=parse&page=" + urllib.parse.quote(page),
                             "license": "owner_waiver", "chars": len(q),
                             "content_hash": hashlib.sha256(q.encode()).hexdigest()[:16]})
            evid.append({"wiki": wiki, "page": page, "ok": True, "bytes": len(wt),
                         "quotes": len(quotes),
                         "sha16": hashlib.sha256(wt.encode()).hexdigest()[:16]})
            print(f"  ✓ {wiki}:{page} {len(wt)//1024}KB → {len(quotes)} 条")
            time.sleep(2.5)

    # 去重
    seen, uniq = set(), []
    for r in rows:
        if r["content_hash"] in seen:
            continue
        seen.add(r["content_hash"])
        uniq.append(r)
    path = OUT / "v9_game_quotes_extra.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in uniq:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = {"rows": len(uniq), "chars": sum(r["chars"] for r in uniq),
           "by_wiki": {}, "evidence": evid,
           "file": str(path.relative_to(ROOT))}
    for r in uniq:
        rep["by_wiki"][r["game"]] = rep["by_wiki"].get(r["game"], 0) + 1
    (OUT / "game_quotes_extra_manifest.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("rows", "chars", "by_wiki")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

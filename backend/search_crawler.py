"""Zero-key search crawler (ledger 0193): direct Bing HTML scraping.

The zero-key DuckDuckGo HTML endpoint started returning 202/anti-bot pages,
so web_search now drives this crawler (Bing returns clean `b_algo` blocks,
no captcha, no key). Best-effort: on any failure the caller falls back to
known documentation roots.
"""
from __future__ import annotations

import re

import httpx

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
_SEARCH_URL = ("https://cn.bing.com/search?q={q}&count={n}"
               "&mkt=zh-CN&setlang=zh-hans&cc=CN")


def parse_bing(html: str, limit: int = 5) -> list[dict]:
    """Extract {title, url, snippet} from Bing b_algo blocks."""
    results: list[dict] = []
    for m in re.finditer(
        r'<li class="b_algo"[\s\S]*?<h2[^>]*>'
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>[\s\S]*?'
        r'<p[^>]*>([\s\S]*?)</p>',
        html,
    ):
        url, title_raw, snippet_raw = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"<[^>]+>", "", title_raw)
        title = re.sub(r"\s+", " ", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet_raw)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if url.startswith("http") and title:
            results.append({"title": title[:160], "url": url, "snippet": snippet[:240]})
        if len(results) >= int(limit):
            break
    return results


def bing_search(query: str, limit: int = 5) -> list[dict]:
    """Live Bing HTML search; returns [] on any anti-bot/network issue."""
    import urllib.parse

    from backend.target_access import _BROWSER_HEADERS  # reuse identical headers

    q = str(query or "").strip()
    if not q:
        return []
    url = _SEARCH_URL.format(q=urllib.parse.quote(q), n=max(1, min(int(limit), 10)))
    try:
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers=_BROWSER_HEADERS) as c:
            r = c.get(url)
            if r.status_code != 200:
                return []
            return parse_bing(r.text, limit=limit)
    except Exception:
        return []


if __name__ == "__main__":
    import json

    out = bing_search("元亨 数字生命", limit=5)
    print(json.dumps(out, ensure_ascii=False, indent=1))

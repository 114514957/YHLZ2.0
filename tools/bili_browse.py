"""Bilibili browser lane for 元亨 (playwright + system Edge).

Everything goes through a dedicated Edge profile under
``cache/bilibili/edge-profile`` so the owner can log in once and keep the
session out of the repo and out of logs. Read-only by design: this tool
searches, opens a video, reads metadata and subtitle tracks, and asks the
local Gemma to write a note that separates facts from opinions. It never
likes, coins, favourites, comments or follows.

Usage:
    python tools/bili_browse.py login [--timeout 300]
    python tools/bili_browse.py whoami
    python tools/bili_browse.py search "关键词" [--limit 8]
    python tools/bili_browse.py watch <url-or-BV> [--no-summarize]
    python tools/bili_browse.py find "关键词" [--limit 8] [--no-summarize]

Notes go to ``cache/bilibili/notes/<bvid>.md`` (raw subtitle JSON beside it).
When a video has no subtitle track the tool says so instead of inventing a
transcript; ASR fallback is a separate step.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE = ROOT / "cache" / "bilibili" / "edge-profile"
NOTES = ROOT / "cache" / "bilibili" / "notes"
PW_TMP = ROOT / "cache" / "tmp" / "pw-temp"
for _d in (PROFILE, NOTES, PW_TMP):
    _d.mkdir(parents=True, exist_ok=True)
# The DSH sandbox historically denies %TEMP% for child processes; Playwright
# needs a writable temp for its artifacts, so pin it to the workspace.
os.environ["TEMP"] = str(PW_TMP)
os.environ["TMP"] = str(PW_TMP)
tempfile.tempdir = str(PW_TMP)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0")
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"
LLM_MODEL = "gemma-4-e4b"

# 明显的营销/盗版/引流标题：发现阶段降权，不代替内容核验。
_JUNK_RE = re.compile(
    r"(激活码|破解|白嫖|免费看|永久(使用|激活)|一键安装|一键激活|加微|私信|"
    r"引流|躺赚|无门槛|搬运|广告|代下|接单|内部渠道|课程资料加|"
    r"免费听|VIP音乐|会员(免费|破解))")


def _context(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(PROFILE), channel="msedge", headless=headless,
        viewport={"width": 1366, "height": 900}, user_agent=UA,
        locale="zh-CN", args=["--disable-blink-features=AutomationControlled"])


def _logged_in(ctx) -> bool:
    try:
        return any(c.get("name") == "SESSDATA" and c.get("value")
                   for c in ctx.cookies("https://www.bilibili.com"))
    except Exception:
        return False


def _bvid(value: str) -> str:
    m = BV_RE.search(str(value or ""))
    return m.group(1) if m else ""


def _pause(a: float = 1.2, b: float = 2.8) -> None:
    time.sleep(random.uniform(a, b))


def _duration_seconds(value: str) -> int:
    parts = [p for p in str(value or "").split(":") if p.strip().isdigit()]
    if not parts:
        return 0
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def _is_junk(title: str) -> bool:
    return bool(_JUNK_RE.search(str(title or "")))


# ---- login / identity ------------------------------------------------------
def cmd_login(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.bilibili.com", timeout=60000,
                  wait_until="domcontentloaded")
        print(json.dumps({"stage": "waiting_for_login",
                          "hint": "请在打开的 Edge 窗口里扫码/登录 B 站"},
                         ensure_ascii=False), flush=True)
        deadline = time.time() + max(30.0, float(args.timeout))
        ok = False
        while time.time() < deadline:
            if _logged_in(ctx):
                ok = True
                break
            time.sleep(2)
        out = {"logged_in": ok}
        if ok:
            try:
                nav = page.request.get(
                    "https://api.bilibili.com/x/web-interface/nav")
                j = nav.json()
                out["uname"] = ((j.get("data") or {}).get("uname") or "")
                out["mid"] = ((j.get("data") or {}).get("mid") or "")
            except Exception:
                pass
        print(json.dumps(out, ensure_ascii=False), flush=True)
        ctx.close()
    return 0 if ok else 1


def cmd_whoami(_args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _context(p, headless=True)
        out = {"logged_in": _logged_in(ctx)}
        if out["logged_in"]:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                nav = page.request.get(
                    "https://api.bilibili.com/x/web-interface/nav")
                j = nav.json().get("data") or {}
                out.update(uname=j.get("uname") or "", mid=j.get("mid") or "",
                           vip=bool((j.get("vipStatus") or 0)))
            except Exception:
                pass
        print(json.dumps(out, ensure_ascii=False))
        ctx.close()
    return 0


# ---- discovery -------------------------------------------------------------
def _search_items(page, keyword: str, limit: int) -> list[dict]:
    url = ("https://search.bilibili.com/all?keyword="
           + urllib.parse.quote(keyword))
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    cards = page.query_selector_all(".bili-video-card")
    items, seen = [], set()
    for card in cards:
        a = card.query_selector("a[href*='/video/BV']")
        href = (a.get_attribute("href") if a else "") or ""
        bv = _bvid(href)
        if not bv or bv in seen:
            continue
        seen.add(bv)
        title_el = card.query_selector(".bili-video-card__info--tit")
        title = ""
        if title_el:
            title = (title_el.get_attribute("title")
                     or title_el.inner_text() or "").strip()
        dur_el = card.query_selector(".bili-video-card__stats__duration")
        duration = dur_el.inner_text().strip() if dur_el else ""
        text = (card.inner_text() or "").strip().splitlines()
        play = text[0].strip() if text and text[0].strip().isdigit() else ""
        date = ""
        for line in text:
            if re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", line.strip()):
                date = line.strip()
        items.append({"bvid": bv, "title": title, "duration": duration,
                      "seconds": _duration_seconds(duration), "play": play,
                      "date": date, "junk": _is_junk(title),
                      "url": f"https://www.bilibili.com/video/{bv}/"})
        if len(items) >= limit:
            break
    return items


def cmd_search(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _context(p, headless=not args.no_headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        items = _search_items(page, args.keyword, args.limit)
        print(json.dumps({"keyword": args.keyword,
                          "logged_in": _logged_in(ctx),
                          "count": len(items), "items": items},
                         ensure_ascii=False, indent=2))
        ctx.close()
    return 0 if items else 1


# ---- watch / note ----------------------------------------------------------
def _capture_player(page) -> dict:
    captured: dict = {}

    def on_response(resp):
        if "/x/player" in resp.url and "v2" in resp.url:
            try:
                captured["json"] = resp.json()
                captured["url"] = resp.url
            except Exception:
                pass

    page.on("response", on_response)
    return captured


def _subtitle_text(page, sub_url: str) -> tuple[str, list]:
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    r = page.request.get(sub_url)
    data = r.json() or {}
    body = data.get("body") or []
    lines = [str(x.get("content") or "").strip() for x in body]
    return " ".join(x for x in lines if x), body


def _llm_chat(messages: list[dict], timeout: float = 180.0) -> str:
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": 0.3,
               "max_tokens": 800, "stream": False}
    req = urllib.request.Request(
        LLM_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    return str(j["choices"][0]["message"]["content"]).strip()


def _llm_summary(meta: dict, text: str, coverage: float) -> str:
    excerpt = text[:3500]
    trunc = len(text) > len(excerpt)
    cover_min = int(coverage // 60)
    lines = [
        f"你是元亨。下面是B站视频《{meta.get('title') or '?'}》"
        f"（UP主：{meta.get('owner') or '?'}）的文字字幕。",
        (f"注意：字幕只覆盖第 1 页前约 {cover_min} 分钟，不是全片。"
         if cover_min else "注意：字幕可能不完整。"),
        ("因为太长，字幕已截断。" if trunc else ""),
        "只依据字幕回答，不要补充字幕之外的知识，不要编造：",
        "1) 一句话概括这段在讲什么；",
        "2) 3-5 个关键点；",
        "3) 把内容分成【事实】【观点】【未证实】三类，每条注明是字幕里的哪句话；",
        "4) 有没有明显的营销话术、夸大或可疑说法（没有就说没有）。",
    ]
    prompt = "\n".join(x for x in lines if x)
    return _llm_chat([
        {"role": "system",
         "content": "你是元亨，说话简洁、诚实，不补充没有依据的内容。"},
        {"role": "user", "content": prompt + "\n\n字幕：\n" + excerpt},
    ])


def _watch_on_page(page, bv: str, summarize: bool = True) -> dict:
    cap = _capture_player(page)
    page.goto(f"https://www.bilibili.com/video/{bv}/", timeout=60000,
              wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    meta: dict = {"bvid": bv,
                  "url": f"https://www.bilibili.com/video/{bv}/"}
    pages = []
    try:
        vj = page.request.get(
            "https://api.bilibili.com/x/web-interface/view?bvid=" + bv).json()
        d = vj.get("data") or {}
        pages = d.get("pages") or []
        meta.update(title=d.get("title") or "",
                    owner=((d.get("owner") or {}).get("name") or ""),
                    duration=d.get("duration") or 0,
                    desc=(d.get("desc") or "")[:500],
                    cid=d.get("cid") or 0)
    except Exception:
        pass
    meta["page_count"] = len(pages)
    meta["p1_duration"] = (pages[0].get("duration") if pages else 0)
    pj = cap.get("json") or {}
    pdata = pj.get("data") or {}
    subs = ((pdata.get("subtitle") or {}).get("subtitles") or [])
    meta["subtitles"] = [
        {"lan": s.get("lan"), "lan_doc": s.get("lan_doc"),
         "url": s.get("subtitle_url")} for s in subs]
    meta["transcript_chars"] = 0
    meta["note"] = ""
    if not subs:
        return meta
    text, body = _subtitle_text(page, subs[0].get("subtitle_url") or "")
    coverage = float(body[-1].get("to") or 0) if body else 0.0
    meta["subtitle_lan"] = subs[0].get("lan_doc") or subs[0].get("lan")
    meta["transcript_chars"] = len(text)
    meta["coverage_seconds"] = round(coverage, 1)
    summary = ""
    if summarize and text:
        summary = _llm_summary(meta, text, coverage)
        meta["summarized"] = not summary.startswith("（本地模型总结失败")
    note = NOTES / f"{bv}.md"
    cover_line = (f"第 1 页 / 共 {meta['page_count']} 页"
                  if meta["page_count"] > 1 else "单页视频")
    parts = [
        f"# {meta.get('title') or bv}", "",
        f"- URL: {meta['url']}",
        f"- UP: {meta.get('owner') or '?'}",
        f"- 时长: {meta.get('duration')}s；覆盖: {cover_line}，"
        f"字幕到 {int(coverage // 60)} 分 {int(coverage % 60)} 秒",
        f"- 字幕: {meta.get('subtitle_lan')}（平台字幕，未核）",
        f"- 抓取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "", "## 字幕原文", "", text, "",
    ]
    if summary:
        parts += ["## 元亨的笔记（本地 Gemma）", "", summary, ""]
    note.write_text("\n".join(parts), encoding="utf-8")
    (NOTES / f"{bv}.subtitle.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")
    meta["note"] = str(note)
    return meta


def cmd_watch(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    bv = _bvid(args.target)
    if not bv:
        print(json.dumps({"error": "not a bilibili BV/url"}, ensure_ascii=False))
        return 2
    with sync_playwright() as p:
        ctx = _context(p, headless=not args.no_headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        meta = _watch_on_page(page, bv, summarize=not args.no_summarize)
        meta["logged_in"] = _logged_in(ctx)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        ctx.close()
    return 0 if meta.get("title") else 1


def cmd_find(args: argparse.Namespace) -> int:
    """Search -> skip obvious junk -> prefer 3-60 min -> watch + note."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _context(p, headless=not args.no_headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        items = _search_items(page, args.keyword, args.limit)
        usable = [it for it in items if not it["junk"]]
        usable.sort(key=lambda it: (not (180 <= it["seconds"] <= 3600),
                                    abs(it["seconds"] - 900)))
        if not usable:
            print(json.dumps({"keyword": args.keyword, "error": "只找到疑似营销/盗版结果",
                              "items": items}, ensure_ascii=False, indent=2))
            ctx.close()
            return 1
        pick = usable[0]
        meta = _watch_on_page(page, pick["bvid"],
                              summarize=not args.no_summarize)
        meta["logged_in"] = _logged_in(ctx)
        meta["picked_from"] = {"keyword": args.keyword,
                               "found": len(items),
                               "usable": len(usable)}
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        ctx.close()
    return 0 if meta.get("title") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login")
    p_login.add_argument("--timeout", type=float, default=300.0)
    p_login.set_defaults(func=cmd_login)

    p_who = sub.add_parser("whoami")
    p_who.set_defaults(func=cmd_whoami)

    p_search = sub.add_parser("search")
    p_search.add_argument("keyword")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.add_argument("--no-headless", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_watch = sub.add_parser("watch")
    p_watch.add_argument("target")
    p_watch.add_argument("--no-summarize", action="store_true")
    p_watch.add_argument("--no-headless", action="store_true")
    p_watch.set_defaults(func=cmd_watch)

    p_find = sub.add_parser("find")
    p_find.add_argument("keyword")
    p_find.add_argument("--limit", type=int, default=10)
    p_find.add_argument("--no-summarize", action="store_true")
    p_find.add_argument("--no-headless", action="store_true")
    p_find.set_defaults(func=cmd_find)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

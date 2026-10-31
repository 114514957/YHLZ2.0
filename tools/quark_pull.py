#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接调夸克网盘 API 拉文件（绕开 AutoPanel 和浏览器下载）。

为什么要这个：实例关机后 SSH 拉不了；AutoPanel 的夸克适配报「未找到该用户」。
夸克网页版自己的接口更直接：列目录 → 取下载链接 → 下载。

Cookie 从环境变量 YH_QUARK_COOKIE 读，**不写进文件**（等于登录凭证）。

用法：
    set YH_QUARK_COOKIE=<从浏览器复制的整条 Cookie>
    python tools/quark_pull.py --list
    python tools/quark_pull.py --find v9t2
    python tools/quark_pull.py --get <fid> --out <path>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://drive-pc.quark.cn/1/clouddrive"
COOKIE = os.environ.get("YH_QUARK_COOKIE", "")

# 本机有系统代理，urllib 默认会走它，对夸克域名会被拒绝（WinError 10061）。
# 显式装一个空 ProxyHandler 的 opener，所有请求都直连。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def headers(extra: dict | None = None) -> dict:
    h = {
        "Cookie": COOKIE,
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
        "Referer": "https://pan.quark.cn/",
        "Origin": "https://pan.quark.cn",
        "Accept": "application/json, text/plain, */*",
    }
    if extra:
        h.update(extra)
    return h


def get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=headers())
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers({
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }), method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 400/403 的响应体通常写明原因（code/message），打出来才能定位
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError("HTTP %s｜%s｜%s" % (e.code, url[:90], body)) from e


def list_dir(pdir: str = "0", page: int = 1, size: int = 100) -> dict:
    qs = urllib.parse.urlencode({
        "pr": "ucpro", "fr": "pc", "uc_param_str": "",
        "pdir_fid": pdir, "_page": page, "_size": size,
        "_fetch_total": 1, "_fetch_sub_dirs": 1,
        "_sort": "file_type:asc,updated_at:desc",
    })
    return get_json("%s/file/sort?%s" % (API, qs))


def walk(pdir: str = "0", depth: int = 0, max_depth: int = 3, out: list | None = None):
    """递归列目录，输出 (fid, name, size, dir_flag, path)。"""
    if out is None:
        out = []
    try:
        d = list_dir(pdir)
    except Exception as e:  # noqa: BLE001
        print("  ⚠ 列 %s 失败：%s" % (pdir, str(e)[:80]))
        return out
    items = (d.get("data") or {}).get("list") or []
    for it in items:
        name = it.get("file_name", "?")
        is_dir = bool(it.get("dir"))
        out.append({"fid": it.get("fid"), "name": name,
                    "size": it.get("size", 0), "dir": is_dir,
                    "path": name, "depth": depth})
        if is_dir and depth < max_depth:
            walk(it.get("fid"), depth + 1, max_depth, out)
    return out


def get_download_url(fid: str) -> str:
    d = post_json("%s/file/download?pr=ucpro&fr=pc&uc_param_str=" % API,
                  {"fids": [fid]})
    data = d.get("data") or []
    if not data:
        raise RuntimeError("取下载链接失败：%s" % json.dumps(d, ensure_ascii=False)[:200])
    return data[0].get("download_url", "")


def download(url: str, dst: str, chunk: int = 1 << 20) -> None:
    req = urllib.request.Request(url, headers={
        "User-Agent": headers()["User-Agent"],
        "Cookie": COOKIE,
        "Referer": "https://pan.quark.cn/",
    })
    t0 = time.time()
    got = 0
    with _OPENER.open(req, timeout=120) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        last = 0
        while True:
            b = r.read(chunk)
            if not b:
                break
            f.write(b)
            got += len(b)
            if got - last > 50 * 1024 * 1024:
                el = time.time() - t0
                print("    %.1f%%｜%.1f MB/s"
                      % (100.0 * got / total if total else 0,
                         got / 1048576 / el if el else 0), flush=True)
                last = got
    el = time.time() - t0
    print("    ✅ %.2f GB｜%.1f 分钟｜%.1f MB/s"
          % (got / 1073741824, el / 60, got / 1048576 / el if el else 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--find", default="", help="按名字关键词找")
    ap.add_argument("--get", default="", help="按 fid 下载")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    if not COOKIE:
        print("❌ 需要环境变量 YH_QUARK_COOKIE")
        return 2
    print("Cookie 长度：%d 字符" % len(COOKIE))

    if a.list or a.find:
        print("\n列目录（递归 3 层）…")
        items = walk()
        print("  共 %d 项" % len(items))
        hit = items
        if a.find:
            hit = [x for x in items if a.find.lower() in x["name"].lower()]
            print("  匹配「%s」：%d 项" % (a.find, len(hit)))
        for it in hit[:40]:
            kind = "DIR " if it["dir"] else "FILE"
            sz = "%.2f GB" % (it["size"] / 1073741824) if it["size"] else ""
            print("  %s %-52s %10s  %s"
                  % (kind, ("  " * it["depth"]) + it["name"], sz, it["fid"]))
        return 0

    if a.get:
        print("\n取下载链接 …")
        url = get_download_url(a.get)
        print("  URL: %s…" % url[:80])
        if not a.out:
            print("❌ 需要 --out")
            return 2
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        print("  下载到 %s" % a.out)
        download(url, a.out)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
